# McDonald's Price Intelligence

## Official Android app investigation (2026-11-02)

The requested source is McDonald's own Android app, with independent **Pickup**
and **Delivery** collections for **Riyadh**. ALBAIK is only a reference for the
existing project integration; its products and prices are not a data source.

Installed `com.mcdonalds.mobileapp` **3.52.0** (82080) from Google Play on the
project emulator. Selected **Saudi Arabia – Central, Northern and Eastern** and
English (UK). The app fails before its home/menu screen with “Oops! Something
went wrong”; repeated attempts produced `D2-T00-WXF-TQO`, `D2-S5I-4NE-84H`, and
`D2-VB4-NTA-1T2`. Retrying, relaunching, setting Riyadh location/timezone, and
using connected Wi-Fi did not resolve it. See the follow-up diagnosis below.

Evidence: [result.json](research/app/2026-11-02/result.json).
Screenshots and screen XML are retained locally and excluded from Git.
No products were collected, no branch or delivery
coverage was verified, and no official-app collection was added to the daily
schedule. Existing HungerStation data remains a separate source.

A working app session is required before observing navigation, product details,
meal/size prices, and image behavior. Once available, implement an isolated
McDonald's collector/database, verify each channel live, then connect the
adapter, collection controls, and sequential daily schedule.

### Follow-up diagnosis

The user confirmed that the app works on their phone but has no Android device
available to connect for collection. McDonald's [official Czech app FAQ](https://www.mcdonalds.cz/kupony-v-aplikaci/faq/lib/)
identifies Android **D2** as a failed device security check. Its recommended
Google Play Integrity checker was installed from Google Play on the emulator.
All three UI checks showed **Fail**; the raw response contained no device
recognition verdict and returned `UNEVALUATED` for app/account/environment
checks. See [sanitized response](research/app/2026-11-02/integrity-response.json).
The corresponding screenshot is retained locally. These results
support a device-validation blocker; they do not expose McDonald's exact
server-side decision. A later cold boot also produced network timeout **N2**.

Inspection of bundled public configuration/URL strings did not identify a
usable Saudi menu interface. A read-only request to the official McDelivery
menu from this server returned **HTTP 403**. Website/app price equivalence has
not been verified. No source substitution, fabricated data, collector, or
scheduled run was introduced. Resume when a working accessible app session or
a verified official app data interface is available.

The website investigation below is historical; current results are above.

**Historical website status: Blocked - site unreachable from this environment (see below).**
No official collector, API research, database, or change-detection logic
exists yet for McDonald's. This folder only holds the isolated
structure future implementation will fill in - see root
[README.md](../../README.md) for the multi-competitor architecture.

## Status of every competitor in this repo

```text
KFC:          Implemented
Burger King:  Implemented
Herfy:        Implemented
Hardee's:     Implemented
McDonald's:   Blocked - see "Known blocker" below
Albaik:       Scaffold only
```

## Known blocker: site unreachable from this environment (2026-08-11)

`https://www.mcdonalds.com/sa/en-sa/riyadh/full-menu.html` (and even the
bare `mcdonalds.com`/`mcdonalds.com.sa` domains) were confirmed
**completely unreachable** from this environment:

- Plain `curl` (both quiet and verbose) timed out with no HTTP response
  at all - not a 4xx/5xx, no response ever returned.
- A headless Chromium session via Playwright also failed to load the page
  (`net::ERR_HTTP2_PROTOCOL_ERROR` observed once), confirming this is not
  a curl-specific issue.
- This is **not a general connectivity problem**: other HTTPS sites
  (`google.com`, `example.com`, and every other competitor in this repo)
  load instantly from the same environment at the same time.
- DNS resolution for `mcdonalds.com` confirms an Akamai edge
  (`akamaiedge.net`) fronting the site - consistent with IP/ASN-reputation
  -based bot-protection blackholing requests from this environment's
  egress IP, common for datacenter/sandbox IP ranges.

This was reported to the user rather than fabricating an implementation.
The user chose to try an alternative source/link for McDonald's KSA menu
data instead of this domain directly, but had not supplied one as of this
write-up - if you have access to a different environment (a residential
IP, a different cloud provider, or a McDonald's-approved data partner
API), the same architecture pattern below still applies once the site (or
an alternative source) is actually reachable.

## What exists here today

```
competitors/mcdonalds/
├── README.md            This file
├── __init__.py
├── config/__init__.py    Empty - no configuration values yet
├── collector/README.md   Empty - will hold Node.js API bootstrap + collection code (see below)
├── backend/__init__.py   Empty - no storage/change-detection code yet
├── research/
│   ├── pickup/           Empty - future Pickup-channel HAR captures / notes go here
│   ├── delivery/         Empty - future Delivery-channel HAR captures / notes go here
│   └── api-map/          Empty - future api-map.json / api-map.md go here
├── data/
│   ├── raw/              Empty - future raw API JSON dumps
│   ├── screenshots/      Empty - future NEW_PRODUCT/NEW_OFFER screenshots
│   ├── logs/              Empty - future collector logs
│   └── database/          Empty - future mcdonalds_monitor.db lives here, isolated from every other competitor
├── exports/                Empty - future Excel exports
└── tests/__init__.py       Empty - no tests yet (nothing to test)
```

Every directory above is empty except for a `.gitkeep` (or, for Python
packages, an `__init__.py` docstring) - see root README.md's Gitignore
section for why. This is deliberate: **nothing in this folder connects to
any live McDonald's website, and nothing here was copied from KFC's
implementation.**

## Isolation

- `competitors/mcdonalds/` never imports from `competitors/kfc/` or any other
  competitor folder. Shared access is provided only through the BFF adapter contract.
- Once implemented, McDonald's's database will live at
  `competitors/mcdonalds/data/database/mcdonalds_monitor.db` - its own file, never
  shared with or written to by another competitor's collector.

## React application

There is no brand-specific UI or official-source collector yet. When a HungerStation snapshot is available, the shared HungerStation adapter exposes this brand through the React/FastAPI application.

## Adding the real implementation later

When McDonald's is implemented, the intended shape (mirroring
`competitors/kfc/`) is:

1. Research McDonald's's public API/HAR captures under `research/pickup/`,
   `research/delivery/`, and `research/api-map/` - never under
   `competitors/kfc/` or any other competitor's folder.
2. Build the Node.js collector under `collector/` (replacing
   `collector/README.md`), following the same API-first,
   Playwright-bootstrap-only-when-required pattern KFC uses - see
   `competitors/kfc/README.md` "Architecture" for the pattern to follow
   (not to copy verbatim - McDonald's's endpoints are unresearched and will
   differ).
3. Build the Python `backend/` (database and change detection) the same way,
   writing only to
   `competitors/mcdonalds/data/database/mcdonalds_monitor.db`.
4. Add or configure a source adapter so the shared React/FastAPI application can expose the brand.
