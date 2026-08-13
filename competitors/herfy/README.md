# Herfy Price Intelligence

**Status: Implemented.** See the root [README.md](../../README.md) for the
multi-competitor architecture this folder is isolated inside of, and
[competitors/kfc/](../kfc/) / [competitors/burger_king/](../burger_king/)
for the sibling implementations this one follows the same
architecture/rigor as.

A local system that monitors Herfy's
([order.herfy.com](https://order.herfy.com)) public menu, prices, and
offers for **one fixed branch in Riyadh**, once a day, for **Pickup** and
**Delivery** kept completely separate. It detects new products, new
offers, price changes, removed/returned products, offer lifecycle changes
between successful runs, shows the result in a local Streamlit dashboard,
and exports daily/monthly/catalog Excel reports.

It is a monitoring tool only: no login, no OTP, no payment, no order is
ever placed - see [Security & compliance](#security--compliance).

> **Isolation:** this folder never imports from `competitors/kfc/`,
> `competitors/burger_king/`, or any other competitor, and nothing outside
> `competitors/herfy/` imports its internals except
> `pages/5_Herfy.py` at the repo root, which only calls `render()` - see
> [Streamlit dashboard](#streamlit-dashboard) below.

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

## Architecture

```
API First (fully public REST + a static CDN JSON, no login/session needed)
  -> Minimal Playwright Bootstrap (app-settings only, no clicking)  (collector/api-bootstrap.js)
  -> direct HTTPS REST/CDN calls                                    (collector/api-client.js)
  -> Playwright Screenshot Capture (NEW_PRODUCT/NEW_OFFER only)      (collector/screenshot-capture.js)
  -> SQLite                                                          (backend/database.py)
  -> Change Detection Engine                                         (backend/change_detector.py)
  -> Streamlit Dashboard (dashboard/page.py, rendered by the
     repo-root pages/5_Herfy.py)
  -> Excel Export                                                    (backend/excel_exporter.py)
```

**Node.js** owns the one-time app-bootstrap, direct REST/CDN collection,
and Playwright screenshots. **Python** owns SQLite, change detection, the
dashboard, Excel export, and the scheduler. `backend/run_service.py` is
the only bridge between them - it invokes `collector/collect.js` and
`collector/screenshot-capture.js` as subprocesses and reads back the JSON
they write to `data/raw/<batch>/`. All paths below are relative to this
folder (`competitors/herfy/`) unless stated otherwise.

Herfy's storefront (`order.herfy.com`) runs on **Solo**
(`api.solo.skylinedynamics.com` / `cdn.getsolo.io`), a third-party
online-ordering SaaS platform - not a Herfy-built backend. Collection
follows this flow for **each** channel independently:

```
app-bootstrap (Playwright, one page load, no clicking)  -> App Key + current menu CDN URL
  -> getLocationsNearby(coords)                          -> confirms the configured branch is nearby and active
     PICKUP: getLocationById -> pickup-enabled / is-open-pickup
     DELIVERY: getLocationById -> delivery-enabled / is-open-deliver
  -> getMenu(menuRefUrl)                                  -> the FULL category/item/modifier tree, with REAL prices
                                                              (no DOM-scrape fallback needed - unlike Burger King)
  -> per-item disable-for-pickup/disable-for-delivery filtering
  -> save with channel=PICKUP or channel=DELIVERY
```

See [research/api-map/api-map.md](research/api-map/api-map.md) for the
full, live-verified endpoint reference, including "How this was verified"
(the one real quirk found: `window.__NUXT__` is a minified IIFE, not
plain JSON - a JS engine must evaluate it, hence the minimal Playwright
bootstrap step) and the real branch/menu-scoping model.

## Folder structure

```
competitors/herfy/
├── README.md                   This file
├── __init__.py                 Makes competitors.herfy a Python package
├── config/                     Reserved for future non-Python declarative
│                                config; current runtime config lives in
│                                backend/config.py (Python) and
│                                collector/config.js (Node) - see below.
├── collector/                   Node.js: app bootstrap + REST/CDN collection + screenshots
│   ├── config.js
│   ├── http-client.js           Dependency-free HTTPS JSON client
│   ├── api-client.js            Typed endpoint wrappers + response schema validation
│   ├── api-bootstrap.js         Playwright: reads the App Key + menu CDN URL (no clicking)
│   ├── channel-collector.js     Shared PICKUP/DELIVERY collection logic
│   ├── pickup-collector.js
│   ├── delivery-collector.js
│   ├── screenshot-capture.js    Playwright: NEW_PRODUCT/NEW_OFFER screenshots only
│   ├── collect.js               CLI entry point (invoked by backend/run_service.py)
│   ├── safe-actions.js          Fail-closed click guard (English + Arabic patterns)
│   └── url-utils.js, logger.js
├── backend/                     Python: storage, detection, export, orchestration
│   ├── config.py
│   ├── database.py              Schema + migrations (identical schema to every competitor - brand-agnostic)
│   ├── models.py                 Shared constants (event types, statuses, offer types)
│   ├── normalizer.py             Raw API product -> normalized snapshot + canonical key
│   ├── offer_parser.py           Three real offer signals - see "Known limitations"
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
├── data/
│   ├── database/
│   │   └── herfy_monitor.db      SQLite database (generated)
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
`competitors.herfy...` package path (not a bare `backend`/`collector`),
and Python resolves that from the **repository root**, Herfy's Python
entry points cannot be run directly from inside this folder (e.g. `cd
competitors/herfy && python run_collector.py` will fail on import).
Always run from the repo root, using one of:

```bash
# Root-level wrappers (recommended):
python run_herfy_collector.py
python run_herfy_collector.py --channel=PICKUP
python run_herfy_collector.py --channel=DELIVERY
python run_herfy_collector.py --no-screenshots
python run_herfy_scheduler.py

# Equivalent module invocations (also from the repo root):
python -m competitors.herfy.run_collector --channel=BOTH
python -m competitors.herfy.scheduler

# Dashboard - the root Streamlit app, then open the "Herfy" page from
# the sidebar (or it's pages/5_Herfy.py directly):
streamlit run app.py
```

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

Requires Node.js 18+ and Python 3.10+.

> If `npx playwright install chromium` reports missing shared libraries on
> Linux, run `sudo npx playwright install-deps` once (needed only for the
> one-time app-bootstrap page load and the screenshot-capture step; every
> menu/branch API call in this collector needs no browser at all).

## Configuration

All configuration lives in the repo-root `.env` (copy from
`.env.example`), namespaced with a `HERFY_` prefix so it never collides
with any other competitor's variables in the same shared file. Every
value has a working default, so the app runs with `.env` untouched:

```ini
HERFY_CITY=Riyadh
HERFY_BRANCH_NAME=RUH - Al Mogarazat - Eirad Plaza Mall 1073
HERFY_LOCATION_ID=29696
HERFY_LATITUDE=24.76017
HERFY_LONGITUDE=46.717525
TIMEZONE=Asia/Riyadh

HERFY_DAILY_RUN_TIME=06:45
HERFY_ENABLE_SCHEDULER=true
```

> **Branch selection note:** RUH - Al Mogarazat - Eirad Plaza Mall 1073
> (locationId `29696`) was confirmed live via `GET /locations/29696` on
> 2026-08-11 to have `status="active"`, `is-open=true`,
> `is-open-pickup=true`, `is-open-deliver=true`, `pickup-enabled=1`,
> `delivery-enabled=1` - see
> [research/api-map/api-map.md](research/api-map/api-map.md) "Branch
> selection". Any of the other 128 branches the same nearby search found
> with both channels enabled and currently open would also work.
> Switching `HERFY_LOCATION_ID` later is safe - history collected under a
> previous id stays in the database (scoped to its own `branch_id`)
> rather than being deleted.

Node (`collector/config.js`) and Python (`backend/config.py`) both read
the **same** `.env` file independently - there is one source of truth for
the branch, but two small loaders (one per language). Both resolve every
other path (data, exports, collector scripts) relative to
`competitors/herfy/` itself, never the repo root and never another
competitor's folder.

## Branch verification

Every run, before collecting anything, calls `GetLocationsNearby` for the
configured coordinates and confirms the configured `HERFY_LOCATION_ID`
appears in the nearby results with `status == "active"`. If this fails,
the run is marked **FAILED immediately** for every requested channel, with
a clear error message, and **no product data from an incomplete/wrong
branch is ever collected or compared**.

Two further, channel-specific checks run per channel, mirroring the
cmsStatus-vs-real-time-open-closed pattern used for every competitor in
this repo:

- **Pickup** calls `GetLocationById` and confirms `pickup-enabled` (a
  structural flag) - `is-open-pickup` (real-time hours) is informational
  only (`branchCurrentlyClosed` on the run), never a reason by itself to
  fail catalog collection.
- **Delivery** calls the same endpoint and confirms `delivery-enabled` -
  `is-open-deliver` is informational only, same reasoning. If either
  structural flag is off for the configured branch, that channel is
  marked FAILED for the run while the other can still succeed
  independently.

## Database

SQLite at `data/database/herfy_monitor.db`, initialized/migrated
automatically by `backend/database.py` on first use (`MIGRATIONS` is an
ordered, append-only list tracked in a `schema_migrations` table - never
edit a shipped migration, only add new ones). The schema itself is
identical to every other competitor's `backend/database.py` - fully
brand-agnostic.

Tables: `branches`, `crawl_runs`, `categories`, `products`,
`product_snapshots`, `product_options`, `offers`, `offer_snapshots`,
`change_events`, `screenshots`, `api_endpoints`. This database holds
**Herfy data only** - no table is shared with, or written to by, any
other competitor.

- **`products`/`offers`** are slowly-changing dimension tables: one row
  per *canonical identity*, tracking `first_seen_at`/`last_seen_at`/
  `consecutive_missing_count`/`status` across the product or offer's
  whole lifetime.
- **`product_snapshots`/`offer_snapshots`** are fact tables: one row **per
  run** per product/offer, with the full normalized field set plus
  `raw_api_json`/`raw_json` (the original API response for that item,
  always available for review, per spec).
- **Product identity** (`canonical_product_key`): primary key is the
  Solo platform's own numeric item `id` (a real catalog id, not a
  generated one); if missing, falls back to normalized name + normalized
  category (see `backend/normalizer.py`). The key always includes
  `branch_id` and `channel`, so a product common to both channels never
  collides into one row.
- **Offer identity** (`offer_key`): falls back to the product's own key
  (no separate promo/coupon id signal exists at the catalog level for
  this brand - see `backend/offer_parser.py`).

## Change Detection Engine

`backend/change_detector.py` is used **verbatim** from every other
competitor's implementation (only the import path differs) - it compares
the **current SUCCESS run** against the **most recent SUCCESS run** for
the same branch+channel, never a PARTIAL or FAILED run on either side.
`run_change_detection()` returns `{"skipped": ...}` immediately for any
non-SUCCESS run, so a schema change or a closed branch can never generate
a false `PRODUCT_REMOVED`/`OFFER_ENDED` wave.

All required event types are implemented and DO fire in practice for this
brand (unlike Burger King's `SPECIAL_PRICE_CHANGED`, which never fires
since no discount signal exists there at all): `NEW_PRODUCT`,
`NEW_IN_CHANNEL`, `NEW_OFFER`, `OFFER_CHANGED`, `OFFER_NOT_OBSERVED`,
`OFFER_ENDED`, `PRICE_INCREASE`, `PRICE_DECREASE`,
`REGULAR_PRICE_CHANGED`, `SPECIAL_PRICE_CHANGED` (fires the moment any
product's `price` drops below its `original-price` - see
`backend/normalizer.py`), `PRODUCT_NOT_OBSERVED`, `PRODUCT_REMOVED`,
`PRODUCT_RETURNED`, `OFFER_RETURNED`, `AVAILABILITY_CHANGED`,
`DETAILS_CHANGED`, `CATEGORY_CHANGED`.

**Not-observed / removed rule** (identical for products and offers):

```
Missing in the first complete successful run:      PRODUCT_NOT_OBSERVED
Missing in two consecutive complete successful runs: remains PRODUCT_NOT_OBSERVED
Missing in three consecutive complete successful runs: PRODUCT_REMOVED
Reappears at any point before the third miss:        cancels the progression, PRODUCT_RETURNED
```

The dashboard never uses the word "Discontinued" - the label is always
**"Removed / Not observed for 3 successful runs"**.

## Excel exports

Generated with `openpyxl` directly (full header styling in Herfy's brand
red, frozen header row, auto-sized columns):

| File | Trigger |
|---|---|
| `exports/Herfy_Daily_Changes_YYYY-MM-DD.xlsx` | "Export Daily Excel" button / `backend.excel_exporter.export_daily_report()` |
| `exports/Herfy_Monthly_Comparison_YYYY-MM.xlsx` | "Export Monthly Excel" button / `export_monthly_report()` |
| `exports/Herfy_Current_Catalog_YYYY-MM-DD.xlsx` | called directly from Python (not currently wired to a dashboard button, same as every other competitor) |

Pickup and Delivery are always separate worksheets in every workbook - no
worksheet ever mixes their prices in one table. The Offers sheets
genuinely populate for this brand (see "Known limitations"). The
**Legacy View** worksheet mirrors the existing Competitors Pricing shape
(`Category | Item | Sandwich | Regular | Medium | Large`) with **real,
CMS-sourced per-size prices** (e.g. Beef Tortilla Meal: Regular=29,
Medium=32, Large=34 SAR, confirmed live) - the best size-price coverage
of any competitor in this repo so far; a product with no confirmed
"Sizes" option group leaves every size column blank rather than guessed.

## Streamlit dashboard

```bash
streamlit run app.py     # from the repo root - see root README.md
```

then open the **Herfy** page from the sidebar (`pages/5_Herfy.py`, a
two-line wrapper: `from competitors.herfy.dashboard.page import render;
render()` - the dashboard code itself lives entirely in
`dashboard/page.py` and is never duplicated in `pages/`).

Local only, no login. Top section shows branch, last successful run, next
scheduled run, and per-channel status; buttons for Run Now / Refresh /
Export Daily Excel / Export Monthly Excel; summary cards for New Products
/ New Offers / Price Increases / Price Decreases / Offers Ended / Not
Observed; tabs for Overview, Pickup Products, Delivery Products, Pickup
Offers, Delivery Offers, Pickup vs Delivery, Changes, and History/Logs
(Price History / Run Logs / Monthly Comparison); sidebar filters for
Category / Name-or-description / Offers Only / Channel / Status / Event
Type / Date.

## Screenshots

`collector/screenshot-capture.js` is invoked **only** for entities the
change detector just classified as `NEW_PRODUCT` or `NEW_OFFER` in the
run that just finished - never for every product every day. Saved to
`data/screenshots/YYYY-MM-DD/PICKUP|DELIVERY/<product_id>_<event_type>_<timestamp>.png`.
Simpler than Burger King's/KFC's: Herfy's menu page shows the full
catalog with no channel/branch selection UI to drive at all, so this
module just loads the storefront page once per batch and locates each
product by name (trying the English name, then the Arabic name - see
"Known limitations" for why the Arabic-first UI makes this best-effort).
If a specific product card cannot be located within the per-job timeout,
the job is recorded as a failure (`screenshots.error`) with the run
continuing normally for every other job. A hard per-run cap
(`MAX_SCREENSHOTS_PER_RUN`, default 40) is a last-resort safety valve, not
the expected normal count.

## Testing

```bash
# From the repo root (pytest.ini's testpaths covers every competitor's tests/):
pytest
pytest competitors/herfy/tests
```

54 tests, all running against a temporary SQLite database and fixture
JSON files under `tests/fixtures/` (real captured product shapes from the
live collector smoke test on branch RUH - Al Mogarazat - Eirad Plaza Mall
1073 / locationId 29696 - no network access, no live site during test
runs). Covers: product-id identity + fallback-by-name/category matching,
real per-size price extraction (`extract_sizes`), the price/
original-price discount logic (including proving it actually fires the
moment a discount appears, not just documentation), Pickup/Delivery
isolation, new product/offer detection, price increase/decrease
(including a 1 SAR change and a `SPECIAL_PRICE_CHANGED` firing test),
offer-not-observed/ended/returned lifecycle, product-removed-after-3-runs,
product-returned (including the cancel-before-third-miss rule),
partial/failed-run-never-generates-missing-events, Excel generation
(including real Offers-sheet rows and real per-size Legacy View prices),
database migrations, scheduler locking (including stale-lock
reclamation), the three-signal offer classifier, and API schema
validation.

The Node collector itself was verified against the **real, live** site
(not just fixtures) during development, via a full `collect.js
--channel=BOTH` run: the app-bootstrap correctly read the App Key and
current menu CDN URL from the live page, `GetLocationsNearby` returned
361 real branches nationwide, `GetLocationById` returned real branch
status/hours/channel flags, and `GetMenu` returned **14 real categories
and 144 real products, every single one already priced** (144/144 - no
DOM-scrape fallback needed) - see `research/api-map/api-map.md`'s "How
this was verified" for the full trail.

## Security & compliance

This system only ever reads public menu/pricing data through the same
public REST API and static CDN file the site's own browser frontend
calls. It never:

- logs in, requests/submits an OTP, or creates an account,
- submits payment or reaches checkout,
- adds anything to a cart (not needed for price/offer monitoring) - the
  safety guard (`collector/safe-actions.js`) explicitly never clicks "Add
  to my orders" (أضف إلى طلباتي) or anything cart-related,
- bypasses CAPTCHA, rate limits, or authorization,
- calls any endpoint not reachable by the public website itself,
- saves cookies, device tokens, or session values to disk/git - the
  `solo-app` App Key is re-read fresh into memory each run, never
  persisted (see `research/api-map/api-map.md` "What is never recorded"),
- saves personal information.

`order.herfy.com/robots.txt` disallows `/checkout/`, `/payment/`,
`/user/`, `/payment-failed` - this collector never requests any of those
paths (it only ever touches `/menu/*` and the Solo REST/CDN endpoints).
Collection uses low concurrency (one Playwright browser/page at a time
for the app-bootstrap and screenshot steps, plain sequential HTTPS calls
otherwise) and reasonable pacing. The fail-closed click guard
(`collector/safe-actions.js` - blocks any click whose text/aria-label/
data-testid matches an order/pay/checkout-style pattern, **in both
English and Arabic** since this brand's UI is Arabic-first) is enforced
on every module that clicks anything (`api-bootstrap.js`,
`screenshot-capture.js`).

## API reference

See [research/api-map/api-map.json](research/api-map/api-map.json)
(machine-readable) and
[research/api-map/api-map.md](research/api-map/api-map.md)
(human-readable) for every endpoint used: method, request shape, required
non-sensitive headers, response schema, and last-verification date.
`GetMenu` and `GetLocationsNearby`/`GetLocationById` were independently
re-verified with a standalone, cookie-less `curl`/`https.request()` (not
just inside a browser) to confirm they truly need no session beyond the
one non-sensitive `solo-app` header.

## Known limitations / what could not be verified

- **`window.__NUXT__` needs a minimal Playwright step, not a pure HTTP
  fetch.** The storefront page's embedded client state is assigned via a
  minified IIFE with webpack/Nuxt-style string-literal deduplication, not
  plain JSON - a JS engine must evaluate it. `api.solo.skylinedynamics.com
  /applications/{id}` looked like a shortcut to get the same App
  Key/menu-CDN-URL without a browser, but returned `401` when tried
  standalone with only the `solo-app` header - a dead end documented in
  `research/api-map/api-map.md` rather than silently re-attempted by a
  future session. `collector/api-bootstrap.js`'s one page load + one
  `page.evaluate()` (no clicking) is the current, working solution.
- **Screenshot capture is best-effort for the Arabic-first UI.** Unlike
  KFC's/Burger King's English-first storefronts, Herfy's default UI
  language is Arabic, so a product card's visible text may render in
  Arabic even though `product_snapshots.product_name_en` is English.
  `screenshot-capture.js` tries the English name first, then the Arabic
  name, and otherwise fails the job the same documented, non-blocking way
  every other competitor's screenshot capture does.
- **No confirmed per-product deep link.** The storefront is a Nuxt SPA;
  no stable, working per-item URL pattern was confirmed live within this
  session (a guessed `/menu/-193160/<id>-<code>` pattern returned `404`).
  `product_url` is stored as `NULL` rather than a guessed link;
  `image_url` (a real, working `cdn.getsolo.io` asset URL) is populated
  and used as the Excel "source link" fallback instead.
- **No active discount was observed anywhere on the 144-item menu at
  verification time** (`price == original-price` on every item, with
  zero exceptions) - `special_price`/`discount_amount`/
  `discount_percentage` are therefore `NULL` in this version's real
  captured data, but the underlying logic (see `backend/normalizer.py`)
  is real field-structure-based logic, not a placeholder, and is
  unit-tested to confirm it correctly reports a discount the moment
  Herfy ever puts one live - see `tests/test_normalizer.py::
  test_normalize_product_reports_a_real_discount_when_price_is_below_original`.
- **`list-price`'s exact purpose was not confirmed** (always `0` across
  the full menu at verification time) - kept in `raw_api_json` for
  forensic reference, never used to compute anything, per the same
  "don't guess" rule applied everywhere else in this project.
- **The Current Full Catalog export is not wired to a dashboard button**,
  same as every other competitor -
  `backend.excel_exporter.export_current_catalog()` is fully implemented
  and covered by a test, call it directly from a Python shell (or add a
  button) if you need it on demand.
