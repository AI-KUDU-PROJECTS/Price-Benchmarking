# KFC Price Intelligence

**Status: Implemented.** The only competitor with a working collector,
database, change-detection engine, dashboard, and Excel exports in this
repo. See the root [README.md](../../README.md) for the multi-competitor
architecture this folder is isolated inside of.

A local system that monitors KFC Saudi's ([saudi.kfc.me](https://saudi.kfc.me))
public menu, prices, and offers for **one fixed branch in Riyadh**, once a
day, for **Pickup** and **Delivery** kept completely separate. It detects
new products, new offers, price changes, offer changes, removed/returned
products, and ended/returned offers between successful runs, shows the
result in a local Streamlit dashboard, and exports daily/monthly/catalog
Excel reports.

It is a monitoring tool only: no login, no OTP, no payment, no order is
ever placed - see [Security & compliance](#security--compliance).

> **Isolation:** this folder never imports from `competitors/hardees/`,
> `competitors/mcdonalds/`, or any other competitor, and nothing outside
> `competitors/kfc/` imports its internals except `pages/1_KFC.py` at the
> repo root, which only calls `render()` - see [Streamlit
> dashboard](#streamlit-dashboard) below.

## Table of contents

- [Architecture](#architecture)
- [Folder structure](#folder-structure)
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
- [Legacy crawler](#legacy-crawler)

## Architecture

```
API First
  -> Playwright Bootstrap only when required   (collector/api-bootstrap.js)
  -> direct HTTPS API calls                     (collector/api-client.js)
  -> Playwright Screenshot Capture              (collector/screenshot-capture.js,
                                                   only for NEW_PRODUCT / NEW_OFFER)
  -> SQLite                                      (backend/database.py)
  -> Change Detection Engine                     (backend/change_detector.py)
  -> Streamlit Dashboard                         (dashboard/page.py, rendered by
                                                   the repo-root pages/1_KFC.py)
  -> Excel Export                                (backend/excel_exporter.py)
```

**Node.js** owns API bootstrap, public API collection, and Playwright
screenshots. **Python** owns SQLite, change detection, the dashboard,
Excel export, and the scheduler. `backend/run_service.py` is the only
bridge between them - it invokes `collector/collect.js` and
`collector/screenshot-capture.js` as subprocesses and reads back the JSON
they write to `data/raw/<batch>/`. All paths below are relative to this
folder (`competitors/kfc/`) unless stated otherwise.

Collection itself follows the required flow for **each** channel
independently:

```
getMenuConfig(orderType=PICKUP|DELIVERY)   -> menuConfigId, clusterId
  -> getMenu(menuConfigId)                 -> category list
  -> getProductsByCategory(id) per category -> products (price, offers, bundles)
  -> save with channel=PICKUP or channel=DELIVERY
```

The channel is fixed by which `getMenuConfig` call started the chain -
never inferred from a `service` field inside a later response. See
[research/api-map/api-map.md](research/api-map/api-map.md) for the full,
live-verified endpoint reference (request/response shapes, header
requirements, and the real API quirks discovered while building this: a
WAF header requirement, two sentinel values - `promoId=-1` and
`specialPrice=0` - that both mean "no active offer" rather than what they
look like at first glance, and the 2026-08-06 branch-selection re-check).

## Folder structure

```
competitors/kfc/
├── README.md                   This file
├── __init__.py                 Makes competitors.kfc a Python package
├── config/                     Reserved for future non-Python declarative
│                                config; current runtime config lives in
│                                backend/config.py (Python) and
│                                collector/config.js (Node) - see below.
├── collector/                   Node.js: API bootstrap + collection + screenshots
│   ├── config.js
│   ├── http-client.js           Dependency-free HTTPS JSON client
│   ├── api-client.js            Typed endpoint wrappers + response schema validation
│   ├── api-bootstrap.js         Playwright: establishes the guest session once
│   ├── channel-collector.js     Shared PICKUP/DELIVERY collection logic
│   ├── pickup-collector.js
│   ├── delivery-collector.js
│   ├── screenshot-capture.js    Playwright: NEW_PRODUCT / NEW_OFFER screenshots only
│   ├── collect.js               CLI entry point (invoked by backend/run_service.py)
│   ├── safe-actions.js          Safety guard (from the original project, still enforced)
│   └── url-utils.js, logger.js, sanitize-har.js
├── backend/                     Python: storage, detection, export, orchestration
│   ├── config.py
│   ├── database.py              Schema + migrations
│   ├── models.py                 Shared constants (event types, statuses, offer types)
│   ├── normalizer.py             Raw API product -> normalized snapshot + canonical key
│   ├── offer_parser.py           Offer detail extraction + offer_type classification
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
├── legacy/                       Original full-journey HAR crawler (superseded, kept for provenance)
├── data/
│   ├── database/
│   │   └── kfc_monitor.db        SQLite database (generated)
│   ├── raw/                      Per-run raw API JSON (generated, gitignored)
│   ├── screenshots/YYYY-MM-DD/PICKUP|DELIVERY/  (generated, gitignored)
│   └── logs/                     Node collector logs (generated, gitignored)
├── exports/                      Generated Excel files (gitignored)
├── run_collector.py              One-shot manual collection run (CLI) - see below for how to invoke
├── scheduler.py                  Independent daily scheduler (APScheduler) - see below
└── tests/                        pytest suite + fixtures (offline, no network)
```

## Running this competitor

Because every module here imports via the fully-qualified
`competitors.kfc...` package path (not a bare `backend`/`collector`), and
Python resolves that from the **repository root**, KFC's Python entry
points cannot be run directly from inside this folder (e.g. `cd
competitors/kfc && python run_collector.py` will fail on import). Always
run from the repo root, using one of:

```bash
# Root-level wrappers (recommended - identical behavior to the old
# single-competitor commands):
python run_kfc_collector.py
python run_kfc_collector.py --channel=PICKUP
python run_kfc_collector.py --channel=DELIVERY
python run_kfc_collector.py --no-screenshots
python run_hungerstation_collector.py
python run_kfc_scheduler.py

# Equivalent module invocations (also from the repo root):
python -m competitors.kfc.run_collector --channel=BOTH
python -m competitors.kfc.scheduler

# Dashboard - the root Streamlit app, then open the "KFC" page from the
# sidebar (or it's pages/1_KFC.py directly):
streamlit run app.py
```

### HungerStation mobile channel

Start the Android emulator and leave the KFC restaurant menu open in the
HungerStation app, then run `python run_hungerstation_collector.py` from the
repository root. The collector reads the Android accessibility hierarchy,
stores a historical snapshot, exposes the data as the `hungerstation`
channel, creates promotions for discounted products, and reuses KFC images
from Pickup or Delivery when the normalized product name matches.

The daily KFC scheduler also runs this mobile collection when
`KFC_HUNGERSTATION_ENABLED=true`. The emulator must stay running and the KFC
menu must remain available. Set `KFC_HUNGERSTATION_ADB_SERIAL` when the device
serial is different from `emulator-5554`.

The Node collector itself has no such restriction (it's invoked as a
subprocess by `backend/run_service.py`, or directly via the root
`package.json` scripts - see [Installation](#installation)).

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

> If `npx playwright install chromium` reports missing shared libraries on
> Linux, run `sudo npx playwright install-deps` once.

## Configuration

All configuration lives in the repo-root `.env` (copy from
`.env.example`) - shared across competitors for now since these variable
names aren't yet namespaced per-competitor and only KFC reads them today
(see root README.md). Every value has a working default, so the app runs
with `.env` untouched. The most relevant ones:

```ini
KFC_CITY=Riyadh
KFC_BRANCH_NAME=RABWAH
KFC_STORE_ID=223
KFC_LATITUDE=24.69040929
KFC_LONGITUDE=46.76410563
TIMEZONE=Asia/Riyadh

DAILY_RUN_TIME=06:00
ENABLE_SCHEDULER=true
```

> **Branch selection note:** RABWAH (storeId=223) replaced the original
> default (SITEEN, storeId=251) on 2026-08-06. SITEEN was closed for
> Pickup at an earlier verification time (a normal operating-hours state,
> not a fault - see "Branch verification" below), so a branch was chosen
> that live-checks confirmed serves **both** Pickup and Delivery, with real
> priced products returned on both channels at verification time. Any of
> the other branches the same check found eligible (DAAERY/128,
> EUROMARCHE/143, HAMZA/165, SOLY/253, OM ELHAMAM/210, NOZHA/206,
> INDUSTRIAL/171 - all in Riyadh) would also work; RABWAH was simply first.
> Switching `KFC_STORE_ID` again later is safe - see "Branch verification"
> for exactly what gets re-checked on the next run, and note that history
> collected under a previous `KFC_STORE_ID` stays in the database (scoped
> to its own `branch_id`) rather than being deleted, and is simply no
> longer shown once the configured id changes.

Node (`collector/config.js`) and Python (`backend/config.py`) both read
the **same** `.env` file independently - there is one source of truth for
the branch, but two small loaders (one per language), matching the
Node/Python split described above. Both resolve every other path (data,
exports, collector scripts) relative to `competitors/kfc/` itself, never
the repo root and never another competitor's folder.

## Branch verification

Every run, before collecting anything, calls `getStoreList` and confirms:

1. The configured city (`KFC_CITY`) exists in the response.
2. The configured `KFC_STORE_ID` exists under that city.
3. That store's `cmsStatus` shows it is still published/configured.

If any of these fail, the run is marked **FAILED immediately** for every
requested channel, with a clear error message, and **no product data from
an incomplete/wrong branch is ever collected or compared**.

Two further, channel-specific checks run per channel:

- **Pickup** calls `getNewStore` with the configured coordinates and
  confirms it resolves to `KFC_STORE_ID`. If it returns the `storeId: 0`
  sentinel, read-only catalog collection may use the configured branch only
  when that same run verified the branch is published and explicitly has
  `services.tak == 1`. A different non-zero branch remains a hard failure,
  preventing prices from being assigned to the wrong location.
- **Delivery** calls `validateLocation` and confirms it resolves to
  `KFC_STORE_ID` and is deliverable. If not, Delivery is marked FAILED for
  that run.

> **Note on `active`/`sdmStatus` vs `cmsStatus`:** live testing found that
> `getStoreList`'s `active`/`sdmStatus` flags reflect the branch's
> real-time open/closed status against its own daily operating hours, NOT
> whether it still exists - `getMenu`/`getProductsByCategory` continue to
> return full, correct catalog data for a "closed" branch. Only
> `cmsStatus` gates the FAILED-run branch-existence check; a closed branch
> is logged as an informational note and never treated as a reason to fail
> read-only catalog collection.

## Database

SQLite at `data/database/kfc_monitor.db`, initialized/migrated
automatically by `backend/database.py` on first use (`MIGRATIONS` is an
ordered, append-only list tracked in a `schema_migrations` table - never
edit a shipped migration, only add new ones).

Tables: `branches`, `crawl_runs`, `categories`, `products`,
`product_snapshots`, `product_options`, `offers`, `offer_snapshots`,
`change_events`, `screenshots`, `api_endpoints`. This database holds
**KFC data only** - no table is shared with, or written to by, any other
competitor.

- **`products`/`offers`** are slowly-changing dimension tables: one row per
  *canonical identity*, tracking `first_seen_at`/`last_seen_at`/
  `consecutive_missing_count`/`status` across the product or offer's whole
  lifetime.
- **`product_snapshots`/`offer_snapshots`** are fact tables: one row **per
  run** per product/offer, with the full normalized field set plus
  `raw_api_json`/`raw_json` (the original API response for that item,
  always available for review, per spec).
- **Product identity** (`canonical_product_key`): primary key is the API's
  numeric product id; if missing, falls back to normalized name +
  normalized category (see `backend/normalizer.py`). The key always
  includes `branch_id` and `channel`, so a product common to both
  channels never collides into one row.
- **Offer identity** (`offer_key`): prefers `promoId`; falls back to the
  product's own key when a discount is active with no separate promo id
  (spec: "A Special Price appears where none existed previously" must
  still count as a new offer).

## Change Detection Engine

`backend/change_detector.py` compares the **current SUCCESS run** against
the **most recent SUCCESS run** for the same branch+channel - never a
PARTIAL or FAILED run on either side, and never the immediately-previous
*calendar day* if that day's run failed; it always finds the last one that
actually succeeded. This is enforced in exactly one place
(`run_change_detection()` returns `{"skipped": ...}` immediately for any
non-SUCCESS run), so a schema change or a closed branch can never generate
a false `PRODUCT_REMOVED`/`OFFER_ENDED` wave.

All required event types are implemented: `NEW_PRODUCT`, `NEW_IN_CHANNEL`,
`NEW_OFFER`, `OFFER_CHANGED`, `OFFER_NOT_OBSERVED`, `OFFER_ENDED`,
`PRICE_INCREASE`, `PRICE_DECREASE`, `REGULAR_PRICE_CHANGED`,
`SPECIAL_PRICE_CHANGED`, `PRODUCT_NOT_OBSERVED`, `PRODUCT_REMOVED`,
`PRODUCT_RETURNED`, `OFFER_RETURNED`, `AVAILABILITY_CHANGED`,
`DETAILS_CHANGED`, `CATEGORY_CHANGED`.

**Not-observed / removed rule** (identical for products and offers): the
dimension table is compared against the CURRENT run's snapshot every time,
not just against the immediately-previous run's snapshot - this is what
lets `consecutive_missing_count` correctly advance 1 -> 2 -> 3 across
non-adjacent successful runs (a bug caught by
`tests/test_change_detector.py::test_product_removed_after_three_consecutive_successful_runs`
during development, before this file was fixed to walk the dimension
table rather than just the previous run's key set).

```
Missing in the first complete successful run:      PRODUCT_NOT_OBSERVED
Missing in two consecutive complete successful runs: remains PRODUCT_NOT_OBSERVED
Missing in three consecutive complete successful runs: PRODUCT_REMOVED
Reappears at any point before the third miss:        cancels the progression, PRODUCT_RETURNED
```

The dashboard never uses the word "Discontinued" - the label is always
**"Removed / Not observed for 3 successful runs"**.

## Excel exports

Generated with `openpyxl` directly (full header styling, frozen header
row, auto-sized columns):

| File | Trigger |
|---|---|
| `exports/KFC_Daily_Changes_YYYY-MM-DD.xlsx` | "Export Daily Excel" button / `backend.excel_exporter.export_daily_report()` |
| `exports/KFC_Monthly_Comparison_YYYY-MM.xlsx` | "Export Monthly Excel" button / `export_monthly_report()` |
| `exports/KFC_Current_Catalog_YYYY-MM-DD.xlsx` | called directly from Python (not currently wired to a dashboard button - see "What could not be verified") |

Pickup and Delivery are always separate worksheets in every workbook - no
worksheet ever mixes their prices in one table. The **Legacy View**
worksheet mirrors the existing Competitors Pricing shape
(`Category | Item | Sandwich | Regular | Medium | Large`); a size is only
ever filled in from `variants[].options[]` data with `isSelected=true` -
if a product has no size variant, those columns are left blank rather than
guessed, and the full, unguessed value stays visible in the corresponding
Normalized worksheet.

## Streamlit dashboard

```bash
streamlit run app.py     # from the repo root - see root README.md
```

then open the **KFC** page from the sidebar (`pages/1_KFC.py`, which is a
two-line wrapper: `from competitors.kfc.dashboard.page import render;
render()` - the dashboard code itself lives entirely in
`dashboard/page.py` and is never duplicated in `pages/`).

Local only, no login (`st.set_page_config(page_title="KFC Price
Intelligence", layout="wide")`, called inside `render()`). Top section
shows branch, last successful run, next scheduled run, and per-channel
status; buttons for Run Now / Refresh / Export Daily Excel / Export
Monthly Excel; summary cards for New Products / New Offers / Price
Increases / Price Decreases / Offers Ended / Not Observed; tabs for
Overview, Pickup Products, Pickup Offers, Delivery Products, Delivery
Offers, Daily Changes, Monthly Comparison, Price History, and Run Logs;
sidebar filters for Date / Channel / Category / Status / Event Type /
Product Name / Offers Only.

## Screenshots

`collector/screenshot-capture.js` is invoked **only** for entities the
change detector just classified as `NEW_PRODUCT` or `NEW_OFFER` in the run
that just finished - never for every product every day. Saved to
`data/screenshots/YYYY-MM-DD/PICKUP|DELIVERY/<product_id>_<event_type>_<timestamp>.png`.
If a specific product card cannot be located on the page within the
per-job timeout, the job is recorded as a failure (`screenshots.error`)
with the run continuing normally for every other job - it never aborts
the batch, matching the spec's "do not fail the entire run" requirement.
A hard per-run cap (`MAX_SCREENSHOTS_PER_RUN`, default 40) is a last-resort
safety valve, not the expected normal count.

## Testing

```bash
# From the repo root (pytest.ini's testpaths covers every competitor's
# tests/ - only KFC has real tests today):
pytest
pytest competitors/kfc/tests
```

47 tests, all running against a temporary SQLite database and fixture
JSON files under `tests/fixtures/` (real, sanitized excerpts of live
API responses - no network access, no live site). Covers: product-id
identity + fallback-by-name/category matching, Pickup/Delivery isolation,
new product/offer detection, price increase/decrease (including a 1 SAR
change), offer-not-observed, offer-ended-after-3-runs,
product-removed-after-3-runs, product/offer-returned,
partial-run-never-generates-missing-events, Excel generation, database
migrations, scheduler locking (including stale-lock reclamation), and API
schema validation.

The Node collector itself was verified against the **real, live** site
(not just fixtures) during development - see
`research/api-map/api-map.md`'s "How this was verified" for the full
trail, including two real API quirks the static analysis alone did not
catch and that only a live run surfaced.

## Security & compliance

This system only ever reads public menu/pricing data through the same
public API the site's own browser frontend calls. It never:

- logs in, requests/submits an OTP, or creates an account,
- submits payment or reaches checkout,
- adds anything to a cart (not needed for price/offer monitoring),
- bypasses CAPTCHA, rate limits, or authorization,
- calls any endpoint not reachable by the public website itself,
- saves cookies, device tokens, or session values to disk/git (see
  `research/api-map/api-map.md` "What is never recorded"),
- saves personal information.

Collection uses low concurrency (one Playwright browser/page at a time,
plain sequential HTTPS calls with a configurable delay between them - see
`DELAY_BETWEEN_REQUESTS` in `.env`) and reasonable pacing. The original
project's safety guard (`collector/safe-actions.js` - the fail-closed click
guard against any "Place Order"/"Pay Now"/OTP/payment-style control) is
preserved verbatim and still enforced on the only module that clicks
anything, `screenshot-capture.js`.

## API reference

See [research/api-map/api-map.json](research/api-map/api-map.json)
(machine-readable) and
[research/api-map/api-map.md](research/api-map/api-map.md)
(human-readable) for every endpoint used: method, request payload,
required non-sensitive headers, response schema, channel/branch
dependency, fields used, and last-verification date. Two endpoints
(`getProductsByCategory`, `getProgressivePromotion`) were reconstructed
from the site's own compiled JS as a first pass and then corrected against
a real live run - both documents explain exactly what changed and why.

## Known limitations / what could not be verified

- **Arabic content is not populated.** `getProductsByCategory` with
  `locale="Ar"` returned HTTP 404 in live testing - simply swapping the
  locale field is not sufficient (see api-map.md's `localeNote`).
  `product_name_ar`, `description_ar`, and `category_name_ar` are always
  `NULL` in this version. Making Arabic collection work would need further
  live investigation into whatever locale-specific `menuConfigId`/
  `clusterId` the site's Arabic UI actually requests, which was outside
  the scope of what could be verified in this session.
- **Calories are never populated.** `nutrition_facts` was an empty array on
  every one of the ~120 real products sampled live - this system stores
  `NULL` rather than guessing, and will start picking the field up
  automatically (no code change needed, see `normalizer.first_present`)
  if a future API response ever does carry it.
- **`getProgressivePromotion`'s populated shape is unconfirmed.** No
  progressive/tiered promotion was active on the live branch during
  verification, so only the empty-result shape (`{"promolist": {}}`) was
  observed; the shape of a real entry is inferred defensively
  (`Object.values(promolist)`) but not confirmed against real data. This
  endpoint is explicitly supplementary and never affects a run's status.
- **`product_url` has no confirmed deep link.** The site is a
  single-page app where product/category views are modal-driven, not
  distinct routes - no per-product URL was confirmed live, so this field
  is stored as `NULL` rather than a guessed link; `image_url` (a real,
  working asset URL) is populated and used as the Excel "source link"
  fallback instead.
- **The Current Full Catalog export is not wired to a dashboard button.**
  `backend.excel_exporter.export_current_catalog()` is fully implemented
  and covered by a test, but `dashboard/page.py`'s button row only exposes
  Daily and Monthly exports per the literal button list in the spec ("Run
  Now / Refresh / Export Daily Excel / Export Monthly Excel") - call it
  directly from a Python shell (or add a button) if you need it on demand.
- **A live end-to-end Pickup run outside the branch's operating hours will
  correctly show FAILED** (see "Branch verification" above) - this was
  observed directly during development and is expected/correct behavior,
  not a bug, but it does mean a manual test run's Pickup result depends on
  the time of day you run it.

## Legacy crawler

`legacy/` holds the project's original full-journey, DOM-scraping HAR
crawler. It is superseded by this system and not run by anything here -
see `legacy/README.md` for why it was kept (it's how the real API
endpoints were originally identified) and what changed underneath it.
