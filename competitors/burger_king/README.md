# Burger King Price Intelligence

**Status: Implemented.** See the root [README.md](../../README.md) for the
multi-competitor architecture this folder is isolated inside of, and
[competitors/kfc/](../kfc/) for the sibling implementation this one
follows the same architecture/rigor as.

A local system that monitors Burger King Saudi's
([burgerking.com.sa](https://burgerking.com.sa/en/)) public menu, prices,
and offers for **one fixed branch in Riyadh**, once a day, for **Pickup**
and **Delivery** kept completely separate. It detects new products, price
changes, removed/returned products between successful runs, shows the
result in a local Streamlit dashboard, and exports daily/monthly/catalog
Excel reports.

It is a monitoring tool only: no login, no OTP, no payment, no order is
ever placed - see [Security & compliance](#security--compliance).

> **Isolation:** this folder never imports from `competitors/kfc/`,
> `competitors/mcdonalds/`, or any other competitor, and nothing outside
> `competitors/burger_king/` imports its internals except
> `pages/4_Burger_King.py` at the repo root, which only calls `render()` -
> see [Streamlit dashboard](#streamlit-dashboard) below.

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
API First (fully public, no auth, no session bootstrap needed at all)
  -> direct HTTPS GraphQL calls                 (collector/api-client.js)
  -> storeMenu pricing (+ plusData audit)       (collector/price-resolver.js)
  -> Playwright DOM price-scrape fallback        (collector/price-scraper.js,
                                                    only for products still unpriced)
  -> Playwright Screenshot Capture               (collector/screenshot-capture.js,
                                                    only for NEW_PRODUCT events)
  -> SQLite                                       (backend/database.py)
  -> Change Detection Engine                      (backend/change_detector.py)
  -> Streamlit Dashboard                          (dashboard/page.py, rendered by
                                                    the repo-root pages/4_Burger_King.py)
  -> Excel Export                                 (backend/excel_exporter.py)
```

**Node.js** owns public API collection, storeMenu pricing, the DOM
price-scrape fallback, and Playwright screenshots. **Python** owns SQLite, change detection, the
dashboard, Excel export, and the scheduler. `backend/run_service.py` is
the only bridge between them - it invokes `collector/collect.js` and
`collector/screenshot-capture.js` as subprocesses and reads back the JSON
they write to `data/raw/<batch>/`. All paths below are relative to this
folder (`competitors/burger_king/`) unless stated otherwise.

Burger King runs on **RBI's (Restaurant Brands International) global
digital ordering platform**, fronted by two independent, fully public,
unauthenticated GraphQL backends - a transactional API
(`euc1-prod-bk-gateway.rbictg.com`) and a Sanity.io CMS
(`czqk28jt.apicdn.sanity.io`). Unlike KFC, **no Playwright session
bootstrap step is needed at all** - every collection endpoint was
confirmed live to work from a plain, cookie-less `https.request()`.
Collection follows this flow for **each** channel independently:

```
GetRestaurants(coords) -> confirms the configured branch is nearby and live
  -> PICKUP: GetRestaurant(storeId)            -> hours/availability
     DELIVERY: DeliveryRestaurant(dropoff)      -> storeStatus + delivery quote
  -> featureMenu()                              -> current Menu document id
  -> GetMenuSections(menuId)                    -> full category/product tree (Sanity CMS,
                                                     NOT store-scoped - same for every branch/channel)
  -> storeMenu(storeId, serviceMode)            -> per-product (+ picker size) prices in cents
  -> price-scraper.js DOM scrape (fallback)     -> only products still missing a price
                                                    (see research/api-map.md "Live prices")
  -> save with channel=PICKUP or channel=DELIVERY
```

See [research/api-map/api-map.md](research/api-map/api-map.md) for the
full, live-verified endpoint reference (request/response shapes, header
requirements, and the real quirks discovered while building this: the
`isAvailable` vs `mobileOrderingStatus` distinction, a nearby-search vs
per-branch-hours disagreement at boundary times, and the corrected
`DeliveryRestaurant` host - see that document's "How this was verified").

## Folder structure

```
competitors/burger_king/
├── README.md                   This file
├── __init__.py                 Makes competitors.burger_king a Python package
├── config/                     Reserved for future non-Python declarative
│                                config; current runtime config lives in
│                                backend/config.py (Python) and
│                                collector/config.js (Node) - see below.
├── collector/                   Node.js: API collection + price scrape + screenshots
│   ├── config.js
│   ├── http-client.js           Dependency-free HTTPS JSON client
│   ├── api-client.js            Typed endpoint wrappers + response schema validation
│   ├── channel-collector.js     Shared PICKUP/DELIVERY collection logic
│   ├── pickup-collector.js
│   ├── delivery-collector.js
│   ├── price-scraper.js         Playwright: DOM price fallback when storeMenu leaves gaps
│   ├── price-resolver.js        Joins storeMenu (+ picker sizes) onto catalog products
│   ├── screenshot-capture.js    Playwright: NEW_PRODUCT screenshots only
│   ├── collect.js               CLI entry point (invoked by backend/run_service.py)
│   ├── safe-actions.js          Fail-closed click guard (same pattern as KFC's)
│   └── url-utils.js, logger.js
├── backend/                     Python: storage, detection, export, orchestration
│   ├── config.py
│   ├── database.py              Schema + migrations (identical schema to KFC's - brand-agnostic)
│   ├── models.py                 Shared constants (event types, statuses, offer types)
│   ├── normalizer.py             Raw API product -> normalized snapshot + canonical key
│   ├── offer_parser.py           Category-based offer detection ("KING DAILY DEALS") - see "Known limitations"
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
│   │   └── burger_king_monitor.db  SQLite database (generated)
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
`competitors.burger_king...` package path (not a bare `backend`/
`collector`), and Python resolves that from the **repository root**,
Burger King's Python entry points cannot be run directly from inside this
folder (e.g. `cd competitors/burger_king && python run_collector.py` will
fail on import). Always run from the repo root, using one of:

```bash
# Root-level wrappers (recommended):
python run_burger_king_collector.py
python run_burger_king_collector.py --channel=PICKUP
python run_burger_king_collector.py --channel=DELIVERY
python run_burger_king_collector.py --no-screenshots
python run_burger_king_scheduler.py

# Equivalent module invocations (also from the repo root):
python -m competitors.burger_king.run_collector --channel=BOTH
python -m competitors.burger_king.scheduler

# Dashboard - the root Streamlit app, then open the "Burger King" page from
# the sidebar (or it's pages/4_Burger_King.py directly):
streamlit run app.py
```

The Node collector itself has no such restriction (it's invoked as a
subprocess by `backend/run_service.py`, or directly via the root
`package.json` scripts - see [Installation](#installation)).

## Installation

`package.json`, `requirements-local.txt`, `node_modules/`, and `.venv/` are all
shared at the **repository root** (see root README.md), not duplicated
per competitor. Install once, from the repo root:

```bash
npm install
npx playwright install chromium
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env
```

Requires Node.js 18+ and Python 3.10+.

> If `npx playwright install chromium` reports missing shared libraries on
> Linux, run `sudo npx playwright install-deps` once (needed only for the
> DOM price-scrape and screenshot steps, which use a real browser; every
> API call in this collector needs no browser at all).

## Configuration

All configuration lives in the repo-root `.env` (copy from
`.env.example`), namespaced with a `BK_` prefix so it never collides with
KFC's or any other competitor's variables in the same shared file. Every
value has a working default, so the app runs with `.env` untouched:

```ini
BK_CITY=Riyadh
BK_BRANCH_NAME=Dabab Street
BK_STORE_ID=11474
BK_LATITUDE=24.7136
BK_LONGITUDE=46.6753
TIMEZONE=Asia/Riyadh

BK_DAILY_RUN_TIME=06:30
BK_ENABLE_SCHEDULER=true
```

> **Branch selection note:** Dabab Street (storeId `11474`) was confirmed
> live via `GetRestaurants` on 2026-08-11 to have
> `mobileOrderingStatus:"live"`, `hasDelivery:true`, `hasTakeOut:true`, and
> real priced products on both Pickup and Delivery at verification time -
> see [research/api-map/api-map.md](research/api-map/api-map.md) "Branch
> selection". Any other branch with `mobileOrderingStatus:"live"` from the
> same nearby search would also work (e.g. Riyadh Park Mall / storeId
> `24452`, Dareen Center / storeId `8260`). Switching `BK_STORE_ID` later
> is safe - history collected under a previous id stays in the database
> (scoped to its own `branch_id`) rather than being deleted.

Node (`collector/config.js`) and Python (`backend/config.py`) both read
the **same** `.env` file independently - there is one source of truth for
the branch, but two small loaders (one per language). Both resolve every
other path (data, exports, collector scripts) relative to
`competitors/burger_king/` itself, never the repo root and never another
competitor's folder.

## Branch verification

Every run, before collecting anything, calls `GetRestaurants` for the
configured coordinates and confirms the configured `BK_STORE_ID` appears
in the nearby results with `mobileOrderingStatus:"live"` (see api-map.md -
`isAvailable` alone is not a reliable "can take an order" signal for this
brand). If this fails, the run is marked **FAILED immediately** for every
requested channel, with a clear error message, and **no product data from
an incomplete/wrong branch is ever collected or compared**.

Two further, channel-specific checks run per channel, mirroring KFC's
cmsStatus-vs-real-time-open-closed pattern:

- **Pickup** calls `GetRestaurant(storeId)` for hours/availability -
  informational (`branchCurrentlyClosed` on the run), never a reason by
  itself to fail catalog collection.
- **Delivery** calls `DeliveryRestaurant(dropoff)` with a placeholder
  address near the branch's own coordinates and confirms
  `storeStatus == "OPEN" && quote == "QUOTE_SUCCESSFUL"`. If not, Delivery
  is marked FAILED for that run while Pickup can still succeed
  independently - live testing found a branch's nearby-search "Open Now"
  state and its own delivery-hours quote can disagree at boundary times
  (see api-map.md), so this collector always checks the channel-specific
  field, never a single generic "is this branch open" flag.

## Database

SQLite at `data/database/burger_king_monitor.db`, initialized/migrated
automatically by `backend/database.py` on first use (`MIGRATIONS` is an
ordered, append-only list tracked in a `schema_migrations` table - never
edit a shipped migration, only add new ones). The schema itself is
identical to [competitors/kfc/backend/database.py](../kfc/backend/database.py) -
fully brand-agnostic.

Tables: `branches`, `crawl_runs`, `categories`, `products`,
`product_snapshots`, `product_options`, `offers`, `offer_snapshots`,
`change_events`, `screenshots`, `api_endpoints`. This database holds
**Burger King data only** - no table is shared with, or written to by,
any other competitor.

- **`products`** is a slowly-changing dimension table: one row per
  *canonical identity*, tracking `first_seen_at`/`last_seen_at`/
  `consecutive_missing_count`/`status` across the product's whole lifetime.
- **`product_snapshots`** is a fact table: one row **per run** per
  product, with the full normalized field set plus `raw_api_json` (the
  original API response for that item, always available for review, per
  spec).
- **Product identity** (`canonical_product_key`): primary key is the
  Sanity document's own `_id` (a stable, real CMS document id, not a
  generated one); if missing, falls back to normalized name + normalized
  category (see `backend/normalizer.py`). The key always includes
  `branch_id` and `channel`, so a product common to both channels never
  collides into one row.
- **`offers`/`offer_snapshots`** are populated for this brand from the
  "KING DAILY DEALS" CMS category (Burger King's own combo-bundle-deals
  section, confirmed live) - see `backend/offer_parser.py` and [Known
  limitations](#known-limitations--what-could-not-be-verified) for exactly
  what is and isn't tracked (no confirmed "before" price exists, so
  `original_price`/`saving_amount`/`discount_percentage` stay `NULL` even
  for these).

## Change Detection Engine

`backend/change_detector.py` is used **verbatim** from
[competitors/kfc](../kfc/backend/change_detector.py) (only the import path
differs) - it compares the **current SUCCESS run** against the **most
recent SUCCESS run** for the same branch+channel, never a PARTIAL or
FAILED run on either side. `run_change_detection()` returns
`{"skipped": ...}` immediately for any non-SUCCESS run, so a schema change
or a closed branch can never generate a false `PRODUCT_REMOVED` wave.

Event types that fire in practice for this brand: `NEW_PRODUCT`,
`NEW_IN_CHANNEL`, `PRICE_INCREASE`, `PRICE_DECREASE`,
`REGULAR_PRICE_CHANGED`, `PRODUCT_NOT_OBSERVED`, `PRODUCT_REMOVED`,
`PRODUCT_RETURNED`, `AVAILABILITY_CHANGED`, `DETAILS_CHANGED`,
`CATEGORY_CHANGED`, and (for "KING DAILY DEALS" products only - see
`backend/offer_parser.py`) `NEW_OFFER`, `OFFER_CHANGED`,
`OFFER_NOT_OBSERVED`, `OFFER_ENDED`, `OFFER_RETURNED`. `SPECIAL_PRICE_CHANGED`
is implemented (same engine as KFC) but never fires for this brand -
`special_price` is always `NULL`, since no confirmed "before" price
exists anywhere in the collected data - see [Known
limitations](#known-limitations--what-could-not-be-verified).

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

Generated with `openpyxl` directly (full header styling in Burger King's
brand red, frozen header row, auto-sized columns):

| File | Trigger |
|---|---|
| `exports/BurgerKing_Daily_Changes_YYYY-MM-DD.xlsx` | "Export Daily Excel" button / `backend.excel_exporter.export_daily_report()` |
| `exports/BurgerKing_Monthly_Comparison_YYYY-MM.xlsx` | "Export Monthly Excel" button / `export_monthly_report()` |
| `exports/BurgerKing_Current_Catalog_YYYY-MM-DD.xlsx` | called directly from Python (not currently wired to a dashboard button, same as KFC) |

Pickup and Delivery are always separate worksheets in every workbook - no
worksheet ever mixes their prices in one table. The Offers sheets list
this brand's "KING DAILY DEALS" combo products (see [Known
limitations](#known-limitations--what-could-not-be-verified) for exactly
what is and isn't tracked - there is no confirmed "before" price, so
Original Price / Saving / Discount % stay blank even there). The
**Legacy View** worksheet mirrors the existing Competitors Pricing shape
(`Category | Item | Sandwich | Regular | Medium | Large`); Burger King's
collected data carries at most a single `itemSize` string per product (not
a multi-option size-variant list like KFC's), so in practice one size
column is filled in per product and the other two are left blank rather
than guessed.

## Streamlit dashboard

```bash
streamlit run app.py     # from the repo root - see root README.md
```

then open the **Burger King** page from the sidebar
(`pages/4_Burger_King.py`, a two-line wrapper: `from
competitors.burger_king.dashboard.page import render; render()` - the
dashboard code itself lives entirely in `dashboard/page.py` and is never
duplicated in `pages/`).

Local only, no login. Top section shows branch, last successful run, next
scheduled run, and per-channel status; buttons for Run Now / Refresh /
Export Daily Excel / Export Monthly Excel; summary cards for New Products
/ New Offers / Price Increases / Price Decreases / Offers Ended / Not
Observed (New Offers / Offers Ended reflect "KING DAILY DEALS" combo
churn - see Known limitations for what's still never populated: Special
Price and any "before" price on an offer); tabs for Overview, Pickup
Products, Delivery Products, Pickup Offers, Delivery Offers, Pickup vs
Delivery, Changes, and History/Logs (Price History / Run Logs / Monthly
Comparison); sidebar filters for Category / Name-or-description / Offers
Only / Channel / Status / Event Type / Date.

## Screenshots

`collector/screenshot-capture.js` is invoked **only** for products the
change detector just classified as `NEW_PRODUCT` in the run that just
finished - never for every product every day (there is no `NEW_OFFER`
case for this brand - see Known limitations). Saved to
`data/screenshots/YYYY-MM-DD/PICKUP|DELIVERY/<product_id>_<event_type>_<timestamp>.png`.
If a specific product card cannot be located on the page within the
per-job timeout, the job is recorded as a failure (`screenshots.error`)
with the run continuing normally for every other job. A hard per-run cap
(`MAX_SCREENSHOTS_PER_RUN`, default 40) is a last-resort safety valve, not
the expected normal count.

## Testing

```bash
# From the repo root (pytest.ini's testpaths covers every competitor's tests/):
pytest
pytest competitors/burger_king/tests
```

52 tests, all running against a temporary SQLite database and fixture
JSON files under `tests/fixtures/` (real captured product shapes from the
live collector smoke test on branch Dabab Street/11474 - no network
access, no live site during test runs). Covers: product-id identity +
fallback-by-name/category matching, the generic modifier/option-group
tree walk, Pickup/Delivery isolation, new product detection, price
increase/decrease (including a 1 SAR change and confirming
`SPECIAL_PRICE_CHANGED` never fires for this brand), new-offer/
offer-not-observed/offer-ended/offer-returned detection for "KING DAILY
DEALS" products (and confirming "KING SAVERS" and a deal-sounding product
NAME in a regular category are both correctly rejected),
product-removed-after-3-runs, product-returned (including the
cancel-before-third-miss rule), partial/failed-run-never-generates-
missing-events, Excel generation (including real Offers-sheet rows and
the never-guessed Legacy View sizes), database migrations, scheduler
locking (including stale-lock reclamation), the category-based offer
classifier, and API schema validation.

The Node collector itself was verified against the **real, live** site
(not just fixtures) during development, via a full `collect.js --channel=BOTH`
run: `GetRestaurants` returned 15 real Riyadh branches, `GetRestaurant`
returned real hours, `featureMenu` resolved a real menu id,
`GetMenuSections` returned 10 real categories and 88 real products,
`DeliveryRestaurant` returned a real `OPEN`/`QUOTE_SUCCESSFUL` quote, and
the price-scraper matched **86/88 Pickup** and **78/88 Delivery** products
to a real on-page SAR price (Delivery prices confirmed genuinely higher
than Pickup for the same product, e.g. KING WRAP BOX 69 SAR delivery vs
49 SAR pickup - a real delivery markup, not a scraping artifact) - see
`research/api-map/api-map.md`'s "How this was verified" for the full
trail. The Delivery price-scrape initially returned 0/88 (see
`collector/price-scraper.js`'s `selectDeliveryAddress()`): after
confirming the "far from this address" dialog, the site shows an async
"We are checking which restaurant will service your address..." step that
was live-observed to take anywhere from ~3s to 10+ seconds before
navigating to `/en/menu` - well past the fixed short wait originally used.
Fixed by polling for the actual `/en/menu` navigation (same
`safe.pollUntil` pattern already used for the nearby-store-card list),
rather than assuming a fixed delay.

## Security & compliance

This system only ever reads public menu/pricing data through the same
public API the site's own browser frontend calls (or, for price, the same
publicly rendered page any visitor sees). It never:

- logs in, requests/submits an OTP, or creates an account,
- submits payment or reaches checkout,
- adds anything to a cart (not needed for price/offer monitoring),
- bypasses CAPTCHA, rate limits, or authorization,
- calls any endpoint not reachable by the public website itself,
- saves cookies, device tokens, or session values to disk/git (`x-session-id`
  is a random UUID generated fresh in memory per run - see
  `research/api-map/api-map.md` "What is never recorded"),
- saves personal information (`DeliveryRestaurant`'s `dropoff.phoneNumber`
  is always sent empty, and the dropoff address used is a placeholder near
  the branch's own public coordinates, never a real customer address).

`burgerking.com.sa/robots.txt` disallows nothing (`Disallow:` is empty),
unlike KFC's site - see `research/api-map/api-map.json`'s `robotsTxt`
field. Collection uses low concurrency (one Playwright browser/page at a
time for the price-scrape and screenshot steps, plain sequential HTTPS
calls otherwise) and reasonable pacing. The fail-closed click guard
(`collector/safe-actions.js` - blocks any click whose text/aria-label/
data-testid matches an order/pay/checkout-style pattern) is enforced on
every module that clicks anything (`price-scraper.js`,
`screenshot-capture.js`).

## API reference

See [research/api-map/api-map.json](research/api-map/api-map.json)
(machine-readable) and
[research/api-map/api-map.md](research/api-map/api-map.md)
(human-readable) for every endpoint used: method, request payload,
required non-sensitive headers, response schema, and last-verification
date. `GetRestaurants`/`GetMenuSections`/`featureMenu` were independently
re-verified with a standalone, cookie-less `https.request()` (not just
inside a browser) to confirm they truly need no session.

## Known limitations / what could not be verified

- **Live prices come from `storeMenu`, not from GetMenuSections.** The
  Sanity menu tree still has **zero price fields**. Store-scoped
  `storeMenu` / `plusData` on the RBI gateway supply cents by entity id /
  PLU; the collector joins them in `price-resolver.js`. DOM scrape is
  only a fallback for SKUs still at 0/missing (some promo items). Picker
  meal sizes (SANDWICH ONLY / GO REGULAR / GO MEDIUM / GO LARGE) and
  piece counts are stored in `sizes` when option ids price successfully.
  See `research/api-map/api-map.md` "Live prices: storeMenu".
- **No confirmed price-discount ("before/after") signal exists anywhere in
  the collected data**, and offers here are NOT identified from a
  product's own name/description text (that rule, established for KFC,
  still applies). Every `discountPlu` field observed across the full menu
  was `null`, no `promoId` field exists, and there is no second price to
  compare against. `special_price`, `promo_id`, `discount_amount`, and
  `discount_percentage` are therefore always `NULL` for every product,
  including offers - see `backend/normalizer.py`.
- **Offers ARE identified for this brand, but by CMS category, not by a
  discount field** (confirmed live 2026-08-11, domain feedback - see
  `backend/offer_parser.py`): "KING DAILY DEALS" is Burger King's own
  dedicated combo-bundle-deals menu section (distinct from its 9 regular
  food categories), so `backend/offer_parser.is_offer_product()` treats
  category membership in it as this brand's one offer signal. The
  superficially similar "KING SAVERS" category was investigated and
  deliberately excluded: its 7 products (HAMBURGER=5 SAR,
  CHEESEBURGER=6 SAR, ...) are confirmed to be Burger King's permanent
  budget/value menu - the individually cheapest core items, not
  time-limited or bundled deals, with the exact same "one flat price, no
  discount signal" shape as any other regular category. Because there is
  still no confirmed "before" price for a KING DAILY DEALS combo (previous
  bullet), `original_price`/`saving_amount`/`discount_percentage` stay
  `NULL` even for these offers - only the offer's name, its one real
  scraped price, and its presence/absence over time (`NEW_OFFER`,
  `OFFER_NOT_OBSERVED`, `OFFER_ENDED`, `OFFER_RETURNED`, price changes) are
  tracked.
- **The modifier/option-group tree walk is generic, not fully modeled.**
  `normalizer.extract_option_groups()` recursively collects any node
  carrying a `modifierMultiplier`/`pluConfigs` key rather than assuming
  one specific GraphQL union shape for every variant (`ItemOption`,
  `Picker` component, combo step, etc.) - the exact schema for every
  variant was not fully mapped in this session. It correctly finds real
  modifier nodes in live-captured data (see `tests/test_normalizer.py`),
  but a future session with the full GraphQL schema (introspection, or
  the site's own compiled type definitions) could model this precisely
  and extract structured option names/prices instead of just presence.
- **Arabic content is populated for products, unlike KFC.** Both
  `name._locFb` and `description._locFbRaw` are present directly in
  `GetMenuSections` (no separate locale-specific request needed) -
  `product_name_ar` and `description_ar` ARE populated in this version.
  `category_name_ar` is always `NULL`, though: `collector/channel-
  collector.js`'s `flattenMenuTree()` only carries each section's English
  `name.locale` down onto its products (`__categoryName`), not the
  sibling `name._locFb` - a small, mechanical fix for a future session,
  not a missing-data problem (the Arabic category name is present in the
  same response, just not threaded through yet).
- **Calories are never populated.** No calorie/nutrition field is present
  anywhere in the products this collector reads (`GetMenuSections`'s
  product shape has no nutrition block wired into the walk here) - this
  system stores `NULL` rather than guessing.
- **`product_url` has no confirmed deep link**, same reasoning as KFC: the
  site is a single-page app with no confirmed stable per-product route.
  `image_url` (a real, working Sanity CDN asset URL) is populated and used
  as the Excel "source link" fallback instead.
- **The Current Full Catalog export is not wired to a dashboard button**,
  same as KFC - `backend.excel_exporter.export_current_catalog()` is fully
  implemented and covered by a test, call it directly from a Python shell
  (or add a button) if you need it on demand.
