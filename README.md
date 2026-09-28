# Price Intelligence

A local, multi-competitor price/offer monitoring repository. Each
competitor is completely isolated inside its own folder under
`competitors/`, with its own collector, database, raw data, screenshots,
exports, and tests. The React/BFF app composes their read-only views, while
the root Streamlit application links to separate operational pages. KUDU is
kept in its own baseline module.

```text
KUDU:         Production menu baseline (delivery and pickup)
KFC:          Implemented
Burger King:  Implemented
Herfy:        Implemented
Hardee's:     Implemented
McDonald's:   Scaffold only (blocked - see competitors/mcdonalds/README.md)
Albaik:       Scaffold only
```

## KUDU baseline

KUDU is the first brand in the React/BFF app and the Streamlit landing page.
The React app opens the KUDU delivery menu by default; pickup is selectable.
Its initial production snapshot lives in `kudu/data/catalog.json` and includes
item names, prices, images, descriptions, calories, and publish flags for both
services. The BFF reads this snapshot without exposing API credentials to the
browser. The full API export from 2026-09-27 is in `exports/`.

To refresh the baseline, set `KUDU_API_USERNAME` and `KUDU_API_PASSWORD` in
`.env` or the shell, then run:

```bash
.venv/bin/python -m kudu.refresh
```

On **Market Overview**, the **Pull data for all competitors** button starts
KUDU and the four connected competitors (KFC, Hardee's, Burger King, Herfy)
at the same time. It collects both channels for each source, shows per-brand
progress, and refreshes the overview when the batch completes. A second click
while a batch is running reuses the active run. Collector output is saved in
`bff/data/pull_logs/<run-id>/`; the competitor batch skips event screenshots
so the parallel job focuses on menu and price data. Each source gets one
retry after a failed or incomplete pass; KUDU also retries transient GET errors.
A pull is marked successful only when its collector confirms completion. The
latest progress is saved locally so a BFF restart marks unfinished work as
interrupted, and the button can start a new pull. Previous complete snapshots
stay available when a source fails. Upstream outages can still make a batch
partial; the page shows which source failed. McDonald's and Albaik remain
outside this action until they have working collectors.

The refresh fetches `menuList` and `itemList` for every menu in delivery and
pickup. It replaces the snapshot only after both services finish and validate.
The production API does not return a currency field; the app displays its
price values as SAR for this Saudi market. Records with `isPublish=false`
remain in the catalog and are visibly marked. A single snapshot provides one
price observation per item; change history starts only when snapshots are
retained and compared in a later collector stage.

## Table of contents

- [KUDU baseline](#kudu-baseline)
- [Multi-competitor architecture](#multi-competitor-architecture)
- [Project structure](#project-structure)
- [Isolation rules](#isolation-rules)
- [Installation](#installation)
- [Running Streamlit](#running-streamlit)
- [Running the KFC collector](#running-the-kfc-collector)
- [Running the Burger King collector](#running-the-burger-king-collector)
- [Running the Herfy collector](#running-the-herfy-collector)
- [Running the Hardee's collector](#running-the-hardees-collector)
- [Adding a new competitor](#adding-a-new-competitor)
- [Gitignore](#gitignore)
- [Security & compliance](#security--compliance)

## Multi-competitor architecture

1. **The repository supports multiple isolated competitors.** Every
   competitor lives entirely under `competitors/<name>/`, with its own
   `config/`, `collector/`, `backend/`, `dashboard/`, `research/`,
   `data/`, `exports/`, and `tests/`. No competitor folder imports from
   another competitor folder, and no competitor's collector writes into
   another competitor's `data/` directory or database.
2. **KFC, Burger King, Herfy, and Hardee's are currently implemented.**
   `competitors/kfc/` has a working Node.js collector (API bootstrap +
   direct API calls + screenshot capture), a Python backend (SQLite,
   change detection, Excel export, scheduler), and a full Streamlit
   dashboard - see [competitors/kfc/README.md](competitors/kfc/README.md).
   `competitors/burger_king/` has the same architecture (Node.js
   collector - fully public/unauthenticated API, no session bootstrap
   needed, plus a Playwright DOM price-scrape fallback and screenshot
   capture; Python backend; Streamlit dashboard) - see
   [competitors/burger_king/README.md](competitors/burger_king/README.md),
   including its own honestly-documented gaps (no live-pricing API found;
   offers are detected by CMS category, not a discount field).
   `competitors/herfy/` again follows the same architecture, on a third,
   completely different underlying ordering platform (Solo /
   `api.solo.skylinedynamics.com`) - a minimal, non-interactive Playwright
   app-bootstrap step, then fully public REST/CDN collection with real
   prices and real per-size prices already in the API response (no
   DOM-scrape fallback needed at all) - see
   [competitors/herfy/README.md](competitors/herfy/README.md).
   `competitors/hardees/` again follows the same architecture, and turned
   out to run on the **exact same Americana-operated platform as KFC**
   (confirmed live: identical endpoint names, blob SAS-token pattern, and
   product shape - only `brand: "hrd"` differs) - see
   [competitors/hardees/README.md](competitors/hardees/README.md) for the
   full shared-platform evidence and the three real bugs found/fixed
   along the way (a UTF-8 BOM on `getStoreList`, an expired TLS
   certificate on the target site itself, and transient `BlobNotFound`
   backend flakiness).
3. **McDonald's and Albaik are not implemented.** McDonald's is
   **blocked**, not merely unstarted - the live site (and even its bare
   domain) was confirmed completely unreachable from this environment,
   consistent with Akamai IP/ASN-reputation bot-protection; see
   [competitors/mcdonalds/README.md](competitors/mcdonalds/README.md)
   "Known blocker" for the full diagnosis. Albaik remains an empty
   scaffold (`__init__.py`, `.gitkeep`, a `collector/README.md`, and a
   `dashboard/page.py` that renders a "Collector not implemented yet"
   message) - no API research, no collector, no database, no live network
   calls exist for it yet.
4. **All competitors meet only through separate pages in the Streamlit
   application.** The root [`app.py`](app.py) is a thin landing page
   (title + competitor list + navigation) with no product data of its
   own. Each competitor has exactly one page under [`pages/`](pages/),
   and each page does nothing but import and call that competitor's own
   `dashboard/page.py::render()` - see [Running
   Streamlit](#running-streamlit).
5. **Each competitor has its own database, raw data, screenshots,
   exports, and tests.** For example:

   ```text
   competitors/kfc/data/database/kfc_monitor.db
   competitors/hardees/data/database/hardees_monitor.db
   competitors/mcdonalds/data/database/mcdonalds_monitor.db
   competitors/burger_king/data/database/burger_king_monitor.db
   competitors/herfy/data/database/herfy_monitor.db
   competitors/albaik/data/database/albaik_monitor.db
   ```

   No database table contains rows from more than one competitor, at any
   stage. Only KFC's, Burger King's, Herfy's, and Hardee's database files
   actually exist today (the other two `data/database/` folders hold a
   `.gitkeep` and nothing else - empty database files are not created
   until each competitor is actually implemented).
6. See [Running Streamlit](#running-streamlit).
7. See [Running the KFC collector](#running-the-kfc-collector),
   [Running the Burger King collector](#running-the-burger-king-collector),
   [Running the Herfy collector](#running-the-herfy-collector), and
   [Running the Hardee's collector](#running-the-hardees-collector).
8. See [Adding a new competitor](#adding-a-new-competitor) for where
   McDonald's (once unblocked) or Albaik's HAR captures and API research
   belong.

## Project structure

```text
price-intelligence/
├── app.py                      Root Streamlit entry point (thin - see above)
├── pages/                       One Streamlit page per competitor
│   ├── 1_KFC.py                 render()s competitors/kfc/dashboard/page.py
│   ├── 2_Hardees.py             render()s competitors/hardees/dashboard/page.py
│   ├── 3_McDonalds.py           placeholder (blocked - see competitors/mcdonalds/README.md)
│   ├── 4_Burger_King.py         render()s competitors/burger_king/dashboard/page.py
│   ├── 5_Herfy.py               render()s competitors/herfy/dashboard/page.py
│   └── 6_Albaik.py              placeholder
├── shared_ui/                   Generic, competitor-agnostic UI helpers only
│   ├── __init__.py
│   ├── layout.py                 page_header(), spacer()
│   ├── components.py              status_badge(), empty_state()
│   └── navigation.py              render_nav_list()
├── competitors/
│   ├── kfc/                      IMPLEMENTED - see competitors/kfc/README.md
│   │   ├── README.md
│   │   ├── config/                (reserved)
│   │   ├── collector/              Node.js: API bootstrap, collection, screenshots
│   │   ├── backend/                Python: SQLite, change detection, Excel export
│   │   ├── dashboard/page.py       render() - the real KFC dashboard
│   │   ├── research/api-map/       api-map.json / api-map.md
│   │   ├── legacy/                 original full-journey crawler (superseded)
│   │   ├── data/{raw,screenshots,logs,database}/
│   │   ├── exports/
│   │   ├── run_collector.py, scheduler.py
│   │   └── tests/
│   │
│   ├── burger_king/               IMPLEMENTED - see competitors/burger_king/README.md
│   │   ├── README.md
│   │   ├── config/                (reserved)
│   │   ├── collector/              Node.js: public API collection, DOM price-scrape fallback, screenshots
│   │   ├── backend/                Python: SQLite, change detection, Excel export
│   │   ├── dashboard/page.py       render() - the real Burger King dashboard
│   │   ├── research/api-map/       api-map.json / api-map.md
│   │   ├── data/{raw,screenshots,logs,database}/
│   │   ├── exports/
│   │   ├── run_collector.py, scheduler.py
│   │   └── tests/
│   │
│   ├── herfy/                     IMPLEMENTED - see competitors/herfy/README.md
│   │   ├── README.md
│   │   ├── config/                (reserved)
│   │   ├── collector/              Node.js: minimal app bootstrap, REST/CDN collection, screenshots
│   │   ├── backend/                Python: SQLite, change detection, Excel export
│   │   ├── dashboard/page.py       render() - the real Herfy dashboard
│   │   ├── research/api-map/       api-map.json / api-map.md
│   │   ├── data/{raw,screenshots,logs,database}/
│   │   ├── exports/
│   │   ├── run_collector.py, scheduler.py
│   │   └── tests/
│   │
│   ├── hardees/                   IMPLEMENTED - see competitors/hardees/README.md
│   │   ├── README.md
│   │   ├── collector/              Node.js: guest-session bootstrap, API collection, screenshots
│   │   ├── backend/                Python: SQLite, change detection, Excel export
│   │   ├── dashboard/page.py       render() - the real Hardee's dashboard
│   │   ├── research/api-map/       api-map.json / api-map.md
│   │   ├── api/, services/, ui/, config/  Superseded live-API-preview research code (unused by dashboard/page.py - see competitors/hardees/README.md)
│   │   ├── data/{raw,screenshots,logs,database}/
│   │   ├── exports/
│   │   ├── run_collector.py, scheduler.py
│   │   └── tests/
│   │
│   ├── mcdonalds/                 BLOCKED - site unreachable from this environment, see competitors/mcdonalds/README.md
│   └── albaik/                     SCAFFOLD ONLY - same empty shape mcdonalds/ started from
│
├── run_kfc_collector.py          Root wrapper -> competitors.kfc.run_collector
├── run_kfc_scheduler.py          Root wrapper -> competitors.kfc.scheduler
├── run_burger_king_collector.py  Root wrapper -> competitors.burger_king.run_collector
├── run_burger_king_scheduler.py  Root wrapper -> competitors.burger_king.scheduler
├── run_herfy_collector.py        Root wrapper -> competitors.herfy.run_collector
├── run_herfy_scheduler.py        Root wrapper -> competitors.herfy.scheduler
├── run_hardees_collector.py      Root wrapper -> competitors.hardees.run_collector
├── run_hardees_scheduler.py      Root wrapper -> competitors.hardees.scheduler
├── package.json / package-lock.json   Shared Node deps (playwright) - see below
├── requirements.txt               Shared Python deps - see below
├── pytest.ini                     testpaths = competitors (discovers every competitor's tests/)
├── .env / .env.example
└── .gitignore
```

Every competitor's `collector/` folder is Node.js, not Python, which is
why it gets a `collector/README.md` placeholder instead of a Python
`__init__.py` in the two remaining scaffolds - matching what KFC's,
Burger King's, Herfy's, and Hardee's real `collector/` folders actually
are (a folder of `.js` files, no `__init__.py` anywhere).

## Isolation rules

- A competitor's Python package (`competitors.<name>.*`) never imports
  `competitors.<other_name>.*`. Verified by `grep -rn "from
  competitors\." competitors/` during development - see the [Validation](#validation-performed)
  notes below for the exact command.
- The only cross-competitor-adjacent code is `shared_ui/`, which contains
  **only** generic visual helpers (page header, status badge, empty
  state, navigation list renderer, spacing) - no product normalization,
  API clients, competitor-specific configuration, pricing calculations,
  change detection, database queries, or competitor names hardcoded into
  its function bodies. Every `shared_ui` function takes its data (titles,
  labels, page paths, statuses) as plain arguments from the caller; the
  actual competitor list lives in `app.py`, not in `shared_ui/`.
- Each competitor's Node.js collector (once implemented) resolves its own
  `node_modules` by walking up from its own folder to the shared
  root-level `node_modules/` - it never reaches into another competitor's
  `collector/` folder to do so, because Node's `require()` resolution is
  based on file location, not on any shared global state.
- `.env` is shared at the repo root for now (KFC's variables are
  unprefixed legacy names; Burger King's, Herfy's, and Hardee's are
  namespaced with `BK_`/`HERFY_`/`HRD_` prefixes precisely so they can
  share this file with KFC's and each other without collision - see
  `competitors/burger_king/backend/config.py`,
  `competitors/herfy/backend/config.py`, and
  `competitors/hardees/backend/config.py`); a future competitor can move
  to its own `.env` under `competitors/<name>/config/` without any
  existing competitor needing to change.

## Installation

`package.json`, `requirements.txt`, `node_modules/`, and the Python
`.venv/` are shared at the repository root (there is one Node/Python
toolchain for the whole repo, even though each competitor's own code
stays isolated):

```bash
npm install
npx playwright install chromium
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Windows:**

```bat
npm install
npx playwright install chromium
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Requires Node.js 18+ and Python 3.10+.

## Running Streamlit

```bash
streamlit run app.py
```

This opens the root landing page (title, competitor list, and one link
per competitor - see [`shared_ui/navigation.py`](shared_ui/navigation.py)).
Pick a competitor from the sidebar or the links on the page:

- **KFC** (`pages/1_KFC.py`) loads the real, working dashboard from
  `competitors/kfc/dashboard/page.py` - full product/offer tables, change
  events, Run Now / Export buttons. See
  [competitors/kfc/README.md](competitors/kfc/README.md) for everything
  it shows.
- **Burger King** (`pages/4_Burger_King.py`) loads the real, working
  dashboard from `competitors/burger_king/dashboard/page.py` - same
  layout as KFC's. See
  [competitors/burger_king/README.md](competitors/burger_king/README.md)
  for everything it shows, including its documented Special Price gap (no
  discount field exists anywhere in this brand's collected data; offers
  are detected by CMS category instead).
- **Herfy** (`pages/5_Herfy.py`) loads the real, working dashboard from
  `competitors/herfy/dashboard/page.py` - same layout again. See
  [competitors/herfy/README.md](competitors/herfy/README.md) for
  everything it shows - this brand has the fewest data gaps of the four:
  real prices, real per-size prices, and a genuinely populated Offers tab.
- **Hardee's** (`pages/2_Hardees.py`) loads the real, working dashboard
  from `competitors/hardees/dashboard/page.py` - same layout again. See
  [competitors/hardees/README.md](competitors/hardees/README.md) for
  everything it shows, including the shared-Americana-platform discovery
  with KFC and the three real bugs found/fixed while building it.
- **McDonald's / Albaik** each show only:

  ```text
  <Competitor> Price Intelligence
  Status: Collector not implemented yet.
  Folder structure is ready for future development.
  ```

  McDonald's real status (blocked, not just unstarted) is documented in
  [competitors/mcdonalds/README.md](competitors/mcdonalds/README.md)
  "Known blocker", not on the placeholder page itself. No KFC data (or
  any other competitor's data) is ever shown on these pages, and no
  combined/cross-competitor table exists anywhere in this repo yet.

## Running the KFC collector

KFC's Python entry points must be run from the **repository root** (see
[competitors/kfc/README.md](competitors/kfc/README.md#running-this-competitor)
for why):

```bash
python run_kfc_collector.py                    # both channels
python run_kfc_collector.py --channel=PICKUP
python run_kfc_collector.py --channel=DELIVERY
python run_kfc_collector.py --no-screenshots    # faster manual test run
python run_kfc_scheduler.py                     # independent daily scheduler, runs forever
```

Both are thin wrappers - `run_kfc_collector.py` imports
`competitors.kfc.run_collector.main`, `run_kfc_scheduler.py` imports
`competitors.kfc.scheduler.main`, and neither adds any logic of its own.
The Streamlit "Run Now" button on the KFC page calls the exact same
`competitors.kfc.backend.run_service.run_collection()` function, guarded
by the same run-lock, so a manual run, a scheduled run, and a
button-triggered run can never race each other.

## Running the Burger King collector

Same pattern as KFC, from the **repository root** (see
[competitors/burger_king/README.md](competitors/burger_king/README.md#running-this-competitor)):

```bash
python run_burger_king_collector.py                    # both channels
python run_burger_king_collector.py --channel=PICKUP
python run_burger_king_collector.py --channel=DELIVERY
python run_burger_king_collector.py --no-screenshots    # faster manual test run
python run_burger_king_scheduler.py                     # independent daily scheduler, runs forever
```

Both are thin wrappers - `run_burger_king_collector.py` imports
`competitors.burger_king.run_collector.main`,
`run_burger_king_scheduler.py` imports
`competitors.burger_king.scheduler.main`, and neither adds any logic of
its own. The Streamlit "Run Now" button on the Burger King page calls the
exact same `competitors.burger_king.backend.run_service.run_collection()`
function, guarded by the same run-lock pattern, so a manual run, a
scheduled run, and a button-triggered run can never race each other -
independently of KFC's own lock, since each competitor's lock file lives
inside its own `competitors/<name>/data/` folder.

## Running the Herfy collector

Same pattern again, from the **repository root** (see
[competitors/herfy/README.md](competitors/herfy/README.md#running-this-competitor)):

```bash
python run_herfy_collector.py                    # both channels
python run_herfy_collector.py --channel=PICKUP
python run_herfy_collector.py --channel=DELIVERY
python run_herfy_collector.py --no-screenshots    # faster manual test run
python run_herfy_scheduler.py                     # independent daily scheduler, runs forever
```

Both are thin wrappers - `run_herfy_collector.py` imports
`competitors.herfy.run_collector.main`, `run_herfy_scheduler.py` imports
`competitors.herfy.scheduler.main`, and neither adds any logic of its
own. Same run-lock isolation as every other competitor - the Streamlit
"Run Now" button on the Herfy page calls the exact same
`competitors.herfy.backend.run_service.run_collection()` function.

## Running the Hardee's collector

Same pattern again, from the **repository root** (see
[competitors/hardees/README.md](competitors/hardees/README.md#running-this-competitor)):

```bash
python run_hardees_collector.py                    # both channels
python run_hardees_collector.py --channel=PICKUP
python run_hardees_collector.py --channel=DELIVERY
python run_hardees_collector.py --no-screenshots    # faster manual test run
python run_hardees_scheduler.py                     # independent daily scheduler, runs forever
```

Both are thin wrappers - `run_hardees_collector.py` imports
`competitors.hardees.run_collector.main`, `run_hardees_scheduler.py`
imports `competitors.hardees.scheduler.main`, and neither adds any logic
of its own. Same run-lock isolation as every other competitor - the
Streamlit "Run Now" button on the Hardee's page calls the exact same
`competitors.hardees.backend.run_service.run_collection()` function.
Hardee's runs on the same underlying Americana platform as KFC (see
[competitors/hardees/README.md](competitors/hardees/README.md#shared-platform-discovery)),
but its lock file, database, and every other piece of state still live
entirely inside `competitors/hardees/` - completely independent of KFC's.

## Adding a new competitor

Albaik remains ready to be filled in following the pattern KFC, Burger
King, Herfy, and Hardee's already demonstrate. McDonald's has the same
scaffold in place too, but is currently **blocked** rather than merely
unstarted - see
[competitors/mcdonalds/README.md](competitors/mcdonalds/README.md) "Known
blocker" before spending time on it in this environment. For example, to
start Albaik:

1. Put Albaik's HAR captures and any API notes under
   `competitors/albaik/research/pickup/`,
   `competitors/albaik/research/delivery/`, and
   `competitors/albaik/research/api-map/` - **never** under
   `competitors/kfc/` or any other competitor's folder, and never copy
   KFC's `api-map.json`/`api-map.md` as a starting point (Albaik's
   endpoints are unresearched and will not match KFC's).
2. Replace `competitors/albaik/collector/README.md` with real Node.js
   collector code, following the same API-first /
   Playwright-bootstrap-only-when-required *pattern*
   `competitors/kfc/collector/` demonstrates (not its literal endpoints) -
   or the fully-public-API pattern Burger King/Herfy/Hardee's demonstrate,
   whichever matches what Albaik's own platform actually needs.
3. Fill in `competitors/albaik/backend/` (database, change detection,
   Excel export), writing only to
   `competitors/albaik/data/database/albaik_monitor.db`.
4. Replace `competitors/albaik/dashboard/page.py`'s placeholder
   `render()` with a real dashboard. `pages/6_Albaik.py` never needs to
   change, since it already just calls `render()`.

This task explicitly did **not** do any of the above for Albaik, and
could not complete it for McDonald's (see the blocker above) - see
`competitors/albaik/README.md` and `competitors/mcdonalds/README.md` for
the exact "what could not be verified / was intentionally not done"
statements.

## Gitignore

Every competitor's generated data is ignored the same way:

```text
competitors/*/data/raw/*
competitors/*/data/screenshots/*
competitors/*/data/logs/*
competitors/*/data/database/*.db
competitors/*/exports/*
```

`.gitkeep` files (and the `__init__.py` scaffolding) stay tracked so the
empty folder structure itself is preserved even though its generated
contents are not.

## Security & compliance

No new API collectors, scraping logic, or network calls were added for
McDonald's (blocked - see its own README) or Albaik (still an empty
scaffold). KFC's existing collector, change-detection rules, offer
classification, and API behavior were not modified - see
[competitors/kfc/README.md](competitors/kfc/README.md#security--compliance)
for its full security/compliance notes (no login, no OTP, no payment, no
cart, no cookies/tokens ever saved to disk or git). Burger King's,
Herfy's, and Hardee's collectors follow the identical set of constraints -
see
[competitors/burger_king/README.md](competitors/burger_king/README.md#security--compliance),
[competitors/herfy/README.md](competitors/herfy/README.md#security--compliance),
and
[competitors/hardees/README.md](competitors/hardees/README.md#security--compliance)
(no login/OTP/payment/cart, no cookies or device/session tokens saved to
disk or git, no real phone number or customer address ever submitted, and
the same fail-closed click guard pattern - extended with Arabic patterns
for Herfy's Arabic-first UI - enforced on every module that clicks
anything). Hardee's additionally required tolerating the target site's
own **expired TLS certificate** (`HRD_IGNORE_TLS_ERRORS`, documented
loudly rather than silently patched over) - see its README's
"Configuration" section.
