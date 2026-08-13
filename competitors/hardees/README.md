# Hardee's Price Intelligence

**Status: Implemented.** See the root [README.md](../../README.md) for the
multi-competitor architecture this folder is isolated inside of, and
[competitors/kfc/](../kfc/) for the sibling implementation this one
follows the same architecture/rigor as.

A local system that monitors Hardee's Saudi's
([saudi.hardees.me](https://saudi.hardees.me)) public menu, prices, and
offers for **one fixed branch in Riyadh**, once a day, for **Pickup** and
**Delivery** kept completely separate. It detects new products/offers,
price changes, removed/returned products between successful runs, shows
the result in a local Streamlit dashboard, and exports daily/monthly/
catalog Excel reports.

It is a monitoring tool only: no login, no OTP, no payment, no order is
ever placed - see [Security & compliance](#security--compliance).

> **Isolation:** this folder never imports from `competitors/kfc/`,
> `competitors/burger_king/`, or any other competitor, and nothing outside
> `competitors/hardees/` imports its internals except
> `pages/2_Hardees.py` at the repo root, which only calls `render()` - see
> [Streamlit dashboard](#streamlit-dashboard) below.

## Table of contents

- [Architecture](#architecture)
- [Shared-platform discovery](#shared-platform-discovery)
- [Folder structure](#folder-structure)
- [Superseded research-phase code](#superseded-research-phase-code)
- [Running this competitor](#running-this-competitor)
- [Installation](#installation)
- [Configuration](#configuration)
- [Branch verification](#branch-verification)
- [Database](#database)
- [Change Detection Engine](#change-detection-engine)
- [Excel exports](#excel-exports)
- [Streamlit dashboard](#streamlit-dashboard)
- [Screenshots](#screenshots)
- [Testing](#testing)
- [Security & compliance](#security--compliance)
- [API reference](#api-reference)
- [Known limitations / what could not be verified](#known-limitations--what-could-not-be-verified)

## Architecture

```
API First (Playwright guest-session bootstrap, then plain HTTPS calls)
  -> guestLogin + getAppConfig                   (collector/api-bootstrap.js)
  -> direct REST calls (getStoreList/getMenu/...) (collector/api-client.js)
  -> Playwright Screenshot Capture                (collector/screenshot-capture.js,
                                                     only for NEW_PRODUCT/NEW_OFFER)
  -> SQLite                                       (backend/database.py)
  -> Change Detection Engine                      (backend/change_detector.py)
  -> Streamlit Dashboard                          (dashboard/page.py, rendered by
                                                     the repo-root pages/2_Hardees.py)
  -> Excel Export                                 (backend/excel_exporter.py)
```

**Node.js** owns session bootstrap, public API collection, and Playwright
screenshots. **Python** owns SQLite, change detection, the dashboard,
Excel export, and the scheduler. `backend/run_service.py` is the only
bridge between them - it invokes `collector/collect.js` and
`collector/screenshot-capture.js` as subprocesses and reads back the JSON
they write to `data/raw/<batch>/`. All paths below are relative to this
folder (`competitors/hardees/`) unless stated otherwise.

## Shared-platform discovery

Hardee's Saudi and [KFC Saudi](../kfc/) are **both operated by Americana
Restaurants ("AMR" / Kuwait Food Co.) on the exact same digital-ordering
platform** - confirmed live 2026-08-11, not assumed:

- Identical endpoint names: `guestLogin`, `getAppConfig`, `getStoreList`,
  `getNewStore`, `validateLocation`, `getMenuConfig`, `getMenu`,
  `getProductsByCategory`, `getHome`, `getProgressivePromotion`.
- Identical Azure Blob Storage SAS-token payload pattern for
  `getAppConfig`, and identical `robots.txt` `Disallow` structure.
- A `kfcloyalty` API namespace is reused **verbatim** for Hardee's own
  loyalty calls - a clear shared-backend artifact, not a coincidence.
- `getMenu`/`getProductsByCategory` need only `brand: "hrd"` instead of
  `brand: "kfc"` in the request payload - every other field, response
  shape, and product structure (`originalPrice`/`specialPrice`/`promoId`/
  `limited_offer`/`steps`/`variants`/`bundleTypeId`) is identical.

This meant `competitors/hardees/backend/normalizer.py` and
`offer_parser.py` are copied from KFC's **near-verbatim** (only the import
path differs - see [research/api-map/api-map.md](research/api-map/api-map.md)
"Shared platform note" for the full evidence trail), and the Node
collector mirrors KFC's module-for-module, with the brand-specific
differences called out below.

Two real domain dead-ends were ruled out before finding the correct one:
`hardees.sa` has an **expired TLS certificate** and redirects to an
unrelated `uae.kfc.me` domain; `hardeesarabia.com` is a hijacked/spam
WordPress site with unrelated German content. The real, live site is
`saudi.hardees.me`.

## Folder structure

```
competitors/hardees/
├── README.md                   This file
├── __init__.py
├── collector/                   Node.js: session bootstrap + API collection + screenshots
│   ├── config.js                 BASE_URL, fixed branch, IGNORE_TLS_ERRORS (see below)
│   ├── http-client.js            Dependency-free HTTPS JSON client (BOM-stripping - see below)
│   ├── api-bootstrap.js          Playwright guest-session bootstrap (blob SAS token, headers)
│   ├── api-client.js             Typed endpoint wrappers (brand="hrd")
│   ├── channel-collector.js      Shared PICKUP/DELIVERY collection logic + BlobNotFound retry
│   ├── pickup-collector.js, delivery-collector.js
│   ├── screenshot-capture.js     Playwright: NEW_PRODUCT/NEW_OFFER screenshots only
│   ├── collect.js                CLI entry point (invoked by backend/run_service.py)
│   ├── safe-actions.js           Fail-closed click guard (same pattern as KFC's)
│   └── url-utils.js, logger.js
├── backend/                     Python: storage, detection, export, orchestration
│   ├── config.py
│   ├── database.py               Schema + migrations (identical schema to KFC's - brand-agnostic)
│   ├── models.py                 Shared constants (event types, statuses, offer types)
│   ├── normalizer.py             Near-verbatim copy of KFC's (confirmed-identical data shape)
│   ├── offer_parser.py           Near-verbatim copy of KFC's (structural signals only)
│   ├── change_detector.py        The Change Detection Engine
│   ├── schema_validator.py       Python-side response-shape validation
│   ├── run_service.py            Orchestration: lock, subprocess calls, ingestion
│   └── excel_exporter.py         Daily / Monthly / Catalog workbooks
├── dashboard/
│   ├── __init__.py
│   └── page.py                   render() - the Streamlit UI; see "Streamlit dashboard"
├── research/
│   └── api-map/
│       ├── api-map.json          Machine-readable endpoint reference
│       └── api-map.md            Human-readable endpoint reference + verification log
├── api/, services/, ui/, config/  Superseded research-phase code - see below, NOT imported by dashboard/page.py anymore
├── data/
│   ├── database/hardees_monitor.db  SQLite database (generated)
│   ├── raw/                      Per-run raw API JSON (generated, gitignored)
│   ├── screenshots/YYYY-MM-DD/PICKUP|DELIVERY/  (generated, gitignored)
│   └── logs/                     Node collector logs (generated, gitignored)
├── exports/                      Generated Excel files (gitignored)
├── run_collector.py              One-shot manual collection run (CLI) - see below for how to invoke
├── scheduler.py                  Independent daily scheduler (APScheduler) - see below
└── tests/                        pytest suite + fixtures (offline, no network)
```

## Superseded research-phase code

An earlier phase of this competitor (before the production
collector/backend/dashboard architecture below existed) built a
**live-API-preview-only** Streamlit page directly against
`api/client.py` + `services/*.py` + `ui/*.py` + `config/` - no database,
no change detection, no scheduler, no offline tests. That code is left in
place for reference (it still works standalone) but **is no longer
imported by `dashboard/page.py`**, which now reads from the real
collector database like every other competitor. If you don't need it for
reference, `api/`, `services/`, `ui/`, and the empty `config/` folder can
be safely deleted.

## Running this competitor

Because every module here imports via the fully-qualified
`competitors.hardees...` package path (not a bare `backend`/`collector`),
and Python resolves that from the **repository root**, Hardee's Python
entry points cannot be run directly from inside this folder (e.g.
`cd competitors/hardees && python run_collector.py` will fail on import).
Always run from the repo root, using one of:

```bash
# Root-level wrappers (recommended):
python run_hardees_collector.py
python run_hardees_collector.py --channel=PICKUP
python run_hardees_collector.py --channel=DELIVERY
python run_hardees_collector.py --no-screenshots
python run_hardees_scheduler.py

# Equivalent module invocations (also from the repo root):
python -m competitors.hardees.run_collector --channel=BOTH
python -m competitors.hardees.scheduler

# Dashboard - the root Streamlit app, then open the "Hardees" page from
# the sidebar (or it's pages/2_Hardees.py directly):
streamlit run app.py
```

## Installation

`package.json`, `requirements.txt`, `node_modules/`, and `.venv/` are all
shared at the **repository root** (see root README.md), not duplicated
per competitor. Install once, from the repo root:

```bash
npm install
npx playwright install chromium
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Requires Node.js 18+ and Python 3.10+.

## Configuration

All configuration lives in the repo-root `.env` (copy from
`.env.example`), namespaced with an `HRD_` prefix so it never collides
with KFC's/BK's/Herfy's variables in the same shared file. Every value has
a working default, so the app runs with `.env` untouched:

```ini
HRD_CITY=Riyadh
HRD_BRANCH_NAME=EUROMARCHE-H
HRD_STORE_ID=24
HRD_LATITUDE=24.70452479
HRD_LONGITUDE=46.66425169
TIMEZONE=Asia/Riyadh

HRD_IGNORE_TLS_ERRORS=true
HRD_DAILY_RUN_TIME=07:00
HRD_ENABLE_SCHEDULER=true
```

> **Branch selection note:** EUROMARCHE-H (storeId `24`) was confirmed
> live 2026-08-11 via `getStoreList` (`cmsStatus:1`, `active:1`,
> `services.del:1`, `services.tak:1`) AND both `getNewStore` (PICKUP) and
> `validateLocation` (DELIVERY, `deliverable:true`) resolving back to
> `storeId:24` for these exact coordinates - see
> [research/api-map/api-map.md](research/api-map/api-map.md) "Branch
> selection". It is the same physical retail location KFC's own
> EUROMARCHE/143 branch uses. Switching `HRD_STORE_ID` later is safe -
> history collected under a previous id stays in the database (scoped to
> its own `branch_id`) rather than being deleted.

> **Known quirk - expired TLS certificate:** `saudi.hardees.me`'s own
> certificate was found **expired** at verification time (2026-08-11,
> `notAfter: Jul 20 2026`) - a real issue on the target site's own
> infrastructure, not this collector's. `HRD_IGNORE_TLS_ERRORS` (default
> `true`) is required for every module that connects to it
> (`api-bootstrap.js`'s Playwright context, `http-client.js`'s direct
> HTTPS calls, `screenshot-capture.js`) - this is flagged loudly in code
> comments rather than silently patched over. Revisit if the certificate
> is ever renewed.

Node (`collector/config.js`) and Python (`backend/config.py`) both read
the **same** `.env` file independently - there is one source of truth for
the branch, but two small loaders (one per language). Both resolve every
other path (data, exports, collector scripts) relative to
`competitors/hardees/` itself, never the repo root and never another
competitor's folder.

## Branch verification

Every run, before collecting anything, `channel-collector.js`'s
`verifyBranchExists()` calls `getStoreList` and confirms the configured
`HRD_STORE_ID` appears with `cmsStatus == 1` and `active == 1`. If this
fails, the run is marked **FAILED immediately** for every requested
channel, with a clear error message, and **no product data from an
incomplete/wrong branch is ever collected or compared**.

**Known quirk - transient `BlobNotFound`:** `getStoreList` is served
straight from Azure Blob Storage (not the app's own API layer) and was
confirmed live to intermittently return HTTP 500 with an Azure
`<Error><Code>BlobNotFound</Code>` XML body that clears itself within 1-2
seconds on retry (3/3 immediate retries succeeded in testing).
`apiClient` calls never throw/reject by design (see `api-client.js`'s
`call()`), so `verifyBranchExists()` retries on the returned schema
validity directly (up to `MAX_RETRIES`, linear backoff) rather than via
`http-client.js`'s exception-based `withRetry()` helper.

Two further, channel-specific checks run per channel, mirroring KFC's
pattern exactly: **Pickup** resolves the branch via `getNewStore`
(`data.storeId`); **Delivery** resolves it via `validateLocation`
(`data.store.storeId`, `deliverable` flag).

## Database

SQLite at `data/database/hardees_monitor.db`, initialized/migrated
automatically by `backend/database.py` on first use. The schema is
identical to [competitors/kfc/backend/database.py](../kfc/backend/database.py) -
fully brand-agnostic.

Tables: `branches`, `crawl_runs`, `categories`, `products`,
`product_snapshots`, `product_options`, `offers`, `offer_snapshots`,
`change_events`, `screenshots`, `api_endpoints`. This database holds
**Hardee's data only** - no table is shared with, or written to by, any
other competitor.

- **`products`** is a slowly-changing dimension table: one row per
  *canonical identity*, tracking `first_seen_at`/`last_seen_at`/
  `consecutive_missing_count`/`status` across the product's whole
  lifetime.
- **`product_snapshots`** is a fact table: one row **per run** per
  product, with the full normalized field set plus `raw_api_json`.
- **Product identity** (`canonical_product_key`): primary key is the
  API's own numeric product id; if missing, falls back to normalized
  name + normalized category (see `backend/normalizer.py`). The key
  always includes `branch_id` and `channel`, so a product common to both
  channels never collides into one row.
- **Offers**: unlike Burger King (category-based) or Herfy (a dedicated
  "Offers" section), Hardee's real discount/promo data is a genuine
  structural field on the product itself - `originalPrice`/
  `specialPrice`/`promoId`/`limited_offer`, exactly like KFC - confirmed
  live via real discounted products such as "Sunday Duo" (24→19 SAR,
  promoId 6739) and "Friday Feast" (137→75 SAR, promoId 6743).
  `backend/offer_parser.is_offer_product()` therefore uses the same
  structural-signal rule as KFC, unmodified.

## Change Detection Engine

`backend/change_detector.py` is used **verbatim** from
[competitors/kfc](../kfc/backend/change_detector.py) (only the import path
differs) - it compares the **current SUCCESS run** against the **most
recent SUCCESS run** for the same branch+channel, never a PARTIAL or
FAILED run on either side. `run_change_detection()` returns
`{"skipped": ...}` immediately for any non-SUCCESS run, so a schema change
or a closed branch can never generate a false `PRODUCT_REMOVED` wave.

**Not-observed / removed rule:**

```
Missing in the first complete successful run:      PRODUCT_NOT_OBSERVED
Missing in two consecutive complete successful runs: remains PRODUCT_NOT_OBSERVED
Missing in three consecutive complete successful runs: PRODUCT_REMOVED
Reappears at any point before the third miss:        cancels the progression, PRODUCT_RETURNED
```

The dashboard never uses the word "Discontinued" - the label is always
**"Removed / Not observed for 3 successful runs"**.

## Excel exports

Generated with `openpyxl` directly (full header styling in Hardee's brand
red, frozen header row, auto-sized columns):

| File | Trigger |
|---|---|
| `exports/Hardees_Daily_Changes_YYYY-MM-DD.xlsx` | "Export Daily Excel" button / `backend.excel_exporter.export_daily_report()` |
| `exports/Hardees_Monthly_Comparison_YYYY-MM.xlsx` | "Export Monthly Excel" button / `export_monthly_report()` |
| `exports/Hardees_Current_Catalog_YYYY-MM-DD.xlsx` | called directly from Python (not currently wired to a dashboard button, same as KFC) |

Pickup and Delivery are always separate worksheets in every workbook - no
worksheet ever mixes their prices in one table. The Normalized sheet's
"Sizes"/"Included Items"/etc. columns render each joined item as clean
text (e.g. "Medium, Large"), never Python's raw dict repr - the same
`_format_join_item()` fix already applied to KFC/Burger King/Herfy is
included here from the start (see `tests/test_excel_exporter.py`'s
regression test).

## Streamlit dashboard

```bash
streamlit run app.py     # from the repo root - see root README.md
```

then open the **Hardees** page from the sidebar (`pages/2_Hardees.py`, a
two-line wrapper: `from competitors.hardees.dashboard.page import
render; render()` - the dashboard code itself lives entirely in
`dashboard/page.py` and is never duplicated in `pages/`).

Local only, no login. Top section shows branch, last successful run, next
scheduled run, and per-channel status; buttons for Run Now / Refresh /
Export Daily Excel / Export Monthly Excel; summary cards for New Products
/ New Offers / Price Increases / Price Decreases / Offers Ended / Not
Observed; tabs for Overview, Pickup Products, Delivery Products, Pickup
Offers, Delivery Offers, Pickup vs Delivery, Changes, and History/Logs
(Price History / Run Logs / Monthly Comparison); sidebar filters for
Category / Name-or-description / Offers Only / Channel / Status / Event
Type / Date - identical layout/labels to KFC/Burger King/Herfy.

## Screenshots

`collector/screenshot-capture.js` is invoked **only** for
products/offers the change detector just classified as `NEW_PRODUCT` or
`NEW_OFFER` in the run that just finished - never for every product every
day. Saved to
`data/screenshots/YYYY-MM-DD/PICKUP|DELIVERY/<product_id>_<event_type>_<timestamp>.png`.

**UI verification performed live 2026-08-11** (see the module's own code
comments for exact detail): the site's real cookie-notice button reads
**"GOT IT"** (not "ACCEPT & CONTINUE" as copied from KFC originally), and
the real hero button reads **"Explore Hardees Menu"** (not "EXPLORE
MENU"). Both were fixed. Critically, **Hardee's top nav has no "Delivery"
tab at all** - only Self-Pickup / Drive-thru / Carhop / Dine-in role="tab"
elements exist. Delivery is instead reached through the separate "SELECT
LOCATION" widget, whose small "SELECT" badge opens a real "Select
Delivery Location" modal containing the genuine `CONFIRM LOCATION`
button - this exact click path was live-verified via Playwright and is
now what `selectChannel()` uses for DELIVERY screenshots.

If a specific product card cannot be located on the page within the
per-job timeout, the job is recorded as a failure (`screenshots.error`)
with the run continuing normally for every other job. A hard per-run cap
(`MAX_SCREENSHOTS_PER_RUN`, default 40) is a last-resort safety valve, not
the expected normal count. See [Known
limitations](#known-limitations--what-could-not-be-verified) for what
this UI verification did **not** confirm.

## Testing

```bash
# From the repo root (pytest.ini's testpaths covers every competitor's tests/):
pytest
pytest competitors/hardees/tests
```

47 tests, all running against a temporary SQLite database and fixture
JSON files under `tests/fixtures/` (test data shaped after the live
collector smoke test on branch EUROMARCHE-H/24 - no network access, no
live site during test runs). Covers: product-id identity + fallback-by-
name/category matching, promoId/specialPrice sentinel handling, Pickup/
Delivery isolation, new product detection, price increase/decrease
(including a 1 SAR change), new-offer/offer-not-observed/offer-ended/
offer-returned detection (structural signal, never by name alone),
product-removed-after-3-runs, product-returned (including the
cancel-before-third-miss rule), partial/failed-run-never-generates-
missing-events, Excel generation (including the Sizes-column
no-dict-repr regression), database migrations, scheduler locking
(including stale-lock reclamation), and API schema validation.

The Node collector itself was verified against the **real, live** site
(not just fixtures) during development, via a full `collect.js
--channel=BOTH` run: session bootstrap succeeded, `getStoreList` resolved
46 real Riyadh branches, `getNewStore`/`validateLocation` both resolved
EUROMARCHE-H/24 for the configured coordinates, `getMenuConfig` resolved
`menuConfigId=HRD_SA_23`/`clusterId=1_8`, and both channels returned
**12/12 categories, 110 real products each, status SUCCESS** - with real
discount/promo products present (Sunday Duo, Monday Double, Friday Feast,
Super Night Deal, Foodie Mix, The Taster Mix, Double Treat Meal).

**The full Python pipeline was also verified against the real, live site**
(not just the Node CLI) via `python run_hardees_collector.py
--channel=BOTH`, run twice in a row a few minutes apart. **Delivery**
succeeded both times (110 products, 66 offers) - the second run's change
detection correctly compared against the first run and reported **zero**
spurious `NEW_PRODUCT`/`NEW_OFFER`/price-change events (nothing had
actually changed between the two runs), confirming the Change Detection
Engine works correctly end to end on real data, not just fixtures.
**Pickup FAILED both times** with a clear, honest reason:
`getNewStore` consistently (4/4 direct re-checks) resolved `storeId: 0`
for the configured coordinates - i.e. EUROMARCHE-H is not currently
resolving as the nearest Pickup branch, even though the identical
coordinates resolve fine for Delivery via `validateLocation`. This is a
**real, live site condition observed at verification time (2026-08-12)**,
not a bug: the exact same coordinates resolved `storeId: 24` for Pickup
during the initial live verification the day before (2026-08-11) - see
[research/api-map/api-map.md](research/api-map/api-map.md)'s "Branch
selection". The system did exactly what it is designed to do here: Pickup
was marked FAILED with a clear error message, zero product/offer rows
were written for it, no false change events were generated, and Delivery
succeeded completely independently - proving the "one channel's failure
never blocks or corrupts the other" requirement holds on real data, not
just in fixture-based tests. If Pickup continues to fail on a future run,
re-run `getStoreList`'s Riyadh branch dump (same method used to find
EUROMARCHE-H originally - see api-map.md) to find a current
Pickup-capable branch and update `HRD_STORE_ID` accordingly, the same way
KFC's own branch was once switched from RABWAH to EUROMARCHE for the same
reason.

## Security & compliance

This system only ever reads public menu/pricing data through the same
public API the site's own browser frontend calls. It never:

- logs in with real credentials, requests/submits an OTP, or creates an
  account,
- submits payment or reaches checkout,
- adds anything to a cart (not needed for price/offer monitoring),
- bypasses CAPTCHA, rate limits, or authorization,
- calls any endpoint not reachable by the public website itself,
- saves cookies, device tokens, or the guest-session `authorization`/
  `refreshtoken` values to disk/git - these are captured live into memory
  for one run only (see `research/api-map/api-map.md` "Security &
  sensitive-data notes").

`saudi.hardees.me/robots.txt` is structurally identical to KFC's own (same
`Disallow` patterns: `*cart*`, `*checkout*`-style, `/Registration`,
`*notification*`, `*forgotpassword*`, `*banners*`). Collection uses low
concurrency (one Playwright browser/page at a time for screenshots, plain
sequential HTTPS calls otherwise) and reasonable pacing
(`DELAY_BETWEEN_REQUESTS`/`DELAY_BETWEEN_PAGES`). The fail-closed click
guard (`collector/safe-actions.js` - blocks any click whose text/
aria-label/data-testid matches an order/pay/checkout/OTP-style pattern)
is enforced on every module that clicks anything.

## API reference

See [research/api-map/api-map.json](research/api-map/api-map.json)
(machine-readable) and
[research/api-map/api-map.md](research/api-map/api-map.md)
(human-readable) for every endpoint used: method, request payload,
required non-sensitive headers, response schema, and last-verification
date.

## Known limitations / what could not be verified

- **The configured Pickup branch does not always resolve.** Live-verified
  2026-08-11 that `getNewStore` resolves `storeId: 24` (EUROMARCHE-H) for
  the configured coordinates for BOTH Pickup and Delivery. Re-verified
  2026-08-12 (see "Testing" above) that `getNewStore` now consistently
  (4/4 direct checks) returns `storeId: 0` for the same coordinates - i.e.
  Pickup is not currently available at this branch - while `validateLocation`
  still resolves the identical coordinates fine for Delivery. The
  collector handles this exactly as designed (Pickup run FAILED with a
  clear message, zero rows written, Delivery unaffected, no false change
  events), so this is not a bug to fix, but it does mean **Pickup data may
  be intermittently unavailable for this specific branch going forward**.
  If it stays unavailable, re-run the branch-discovery method in
  `research/api-map/api-map.md` "Branch selection" to find a
  currently-Pickup-capable branch and update `HRD_STORE_ID`, the same way
  KFC's own branch was once switched from RABWAH to EUROMARCHE.
- **Delivery screenshot capture opens the address modal but does not
  confirm a real address inside it.** The "SELECT LOCATION" → "Select
  Delivery Location" modal → `CONFIRM LOCATION` click path was
  live-verified (see "Screenshots" above), but no address was
  typed/selected before clicking Confirm, so the resulting screenshot's
  visible menu content is not guaranteed to reflect a delivery-specific
  price for every product. This never affects the actual **price data**
  collected (that always comes from the independently-verified direct-API
  collector, `channel-collector.js`), only the illustrative screenshot -
  acceptable given screenshots are a best-effort, non-blocking feature by
  design (spec: "Do not fail the entire run").
- **PICKUP's "USE MY LOCATION"/"PROCEED" branch-confirmation dialog
  (inside `screenshot-capture.js`) was copied from KFC's own confirmed
  flow and was not independently re-verified against Hardee's live UI** -
  Self-Pickup is already the default-selected tab on page load, so a
  working screenshot is still captured (from the homepage) even if
  neither button ever appears; a future session could confirm the exact
  branch-picker dialog text if a more specific Pickup screenshot (past a
  particular branch-confirmation step) is needed.
- **The homepage's own "EXPLORE MENU" widget shows a small, hand-curated
  set of category shortcuts (Deals / Thick Burger / Chicken Burger /
  Chargrilled Burger / Sides & Beverages), not the full 12 real API
  categories** (What's New/ Tornado, Deal of the Day, App Exclusive,
  etc.) - `openCategory()`'s exact-text category-tab search will not find
  a match for most of the 12 real category names unless the browser has
  first navigated to a fuller menu view. The screenshot job still
  succeeds via the full-viewport-screenshot fallback in that case (never
  a hard failure), but the resulting image will show the homepage rather
  than a specific category rail. Confirming the exact click path from the
  homepage into the full category-tabbed menu view (a `View All` link was
  observed but not confirmed clickable during this session) is left for a
  future session.
- **`product_url` has no confirmed deep link**, same reasoning as KFC: no
  confirmed stable per-product route was found. `image_url` (a real,
  working Azure Blob CDN asset URL) is populated and used as the Excel
  "source link" fallback instead.
- **Calories/Arabic name are never populated**, same as KFC - no
  calorie/nutrition field or Arabic name field exists on the
  `getProductsByCategory` response this collector reads; this system
  stores `NULL` rather than guessing.
- **The Current Full Catalog export is not wired to a dashboard button**,
  same as KFC - `backend.excel_exporter.export_current_catalog()` is
  fully implemented and covered by a test, call it directly from a Python
  shell (or add a button) if you need it on demand.
