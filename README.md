# KUDU Price Benchmark

Internal price and promotion monitoring for KUDU Marketing.

## Supported application

The supported product is one React application backed by one FastAPI BFF:

```text
Browser -> React -> FastAPI BFF -> adapters -> source databases/files
```

Start both services locally with:

```bash
python run_dev.py
```

The React/FastAPI application is the only UI. The former Streamlit application,
pages, dashboards, UI helpers, and Streamlit-only dependencies have been
removed. UI work belongs in `frontend/`, and HTTP/API work belongs in `bff/`
or `adapters/`.

Each source collector remains isolated under `competitors/<source>/` with its
own raw data and database. Shared orchestration belongs in
`competitors/shared/` so the same runner or scheduler logic is not copied for
every brand.

```text
KUDU:         Production menu baseline (delivery and pickup)
KFC:          Implemented
Burger King:  Implemented
Herfy:        Implemented
Hardee's:     Implemented
McDonald's:   HungerStation data only; official source blocked
AlBaik:       HungerStation data only; official source not implemented
```

## KUDU baseline

KUDU is the baseline brand in the React/BFF app.
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
- [Running the application](#running-the-application)
- [Running the KFC collector](#running-the-kfc-collector)
- [Running the Burger King collector](#running-the-burger-king-collector)
- [Running the Herfy collector](#running-the-herfy-collector)
- [Running the Hardee's collector](#running-the-hardees-collector)
- [Adding a new competitor](#adding-a-new-competitor)
- [Gitignore](#gitignore)
- [Security & compliance](#security--compliance)

## Multi-competitor architecture

- `frontend/` is the only user interface.
- `bff/` exposes the market, brand, history, Playground, collection-status, and Excel export APIs.
- `adapters/` translates each source into the shared BFF contract. Official-source SQLite adapters use `SQLiteMonitorAdapter`; KUDU and HungerStation keep source-specific adapters.
- `competitors/shared/` contains the common runner, scheduler, data models, schema validation, change detection, and SQLite schema.
- Each implemented official collector keeps only source-specific configuration, normalization, offer parsing, ingestion details, data, and tests under its brand folder.
- KFC, Hardee's, Burger King, and Herfy are connected. McDonald's and AlBaik currently use HungerStation data only.

## Project structure

```text
frontend/                    React application
bff/                         FastAPI routes and application services
adapters/                    Shared BFF source contract and adapters
competitors/shared/          Reusable collector/backend infrastructure
competitors/<brand>/         Source-specific collector logic, data, and tests
kudu/                        KUDU catalog refresh and baseline data
run_dev.py                   Local React + FastAPI launcher
run_<brand>_collector.py     Manual collector entry points
run_<brand>_scheduler.py     Scheduled collector entry points
```

## Isolation rules

- Brand packages do not import one another. Reusable code is imported from
  `competitors.shared` and configured by each brand's thin wrapper.
- Each collector writes only to its own raw-data, log, image, export, and
  SQLite locations.
- The BFF is the composition boundary: adapters expose every source through
  one stable contract without coupling the React application to source schemas.
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

`package.json`, `requirements-local.txt`, `node_modules/`, and the Python
`.venv/` are shared at the repository root (there is one Node/Python
toolchain for the whole repo, even though each competitor's own code
stays isolated):

```bash
npm install
npx playwright install chromium
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env
```

**Windows:**

```bat
npm install
npx playwright install chromium
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-local.txt
copy .env.example .env
```

Requires Node.js 18+ and Python 3.10+.

## Running the application

```bash
python run_dev.py
```

The React application provides market overview, menus, promotions, price changes, history, Product Matching, manual collection controls, and Excel export. Collector CLI and scheduler commands remain available for operations and troubleshooting.

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
Market Overview calls the same `competitors.kfc.backend.run_service.run_collection()` function, guarded
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
its own. Market Overview calls the exact same `competitors.burger_king.backend.run_service.run_collection()`
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
own. The Market Overview pull uses the same `competitors.herfy.backend.run_service.run_collection()` function.

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
of its own. The Market Overview pull uses the same `competitors.hardees.backend.run_service.run_collection()` function.
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
