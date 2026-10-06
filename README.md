# KUDU Price Benchmark

Internal price and promotion monitoring for KUDU Marketing. React is the only
frontend, and FastAPI is the application backend.

```text
Browser → React → FastAPI BFF → adapters → source databases/catalogs
```

## Sources

| Source | Collection path |
| --- | --- |
| KUDU | KUDU API/catalog baseline |
| KFC | Official-source collector |
| Hardee's | Official-source collector |
| Burger King | Official-source collector |
| Herfy | Official-source collector |
| HungerStation | Android Emulator through ADB |

McDonald's and AlBaik currently have HungerStation data only. Their official
source packages remain scaffolds, not connected collectors.

## Install

Requires Python 3.12 and Node.js 18 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
cp .env.example .env
```

The root npm workspace installs both the React dependencies and the shared
Playwright dependency used by the Node.js collectors. Its post-install step
installs Chromium under `.playwright-browsers/`.

On Windows, activate the environment with `.venv\Scripts\activate` and copy
the env file with `copy .env.example .env`.

## Run

Use `manage.py` from the repository root:

```bash
python manage.py dev
python manage.py api

python manage.py collect all
python manage.py collect kfc
python manage.py collect hardees
python manage.py collect burger-king
python manage.py collect herfy
python manage.py collect hungerstation

python manage.py schedule kfc
python manage.py schedule hardees
python manage.py schedule burger-king
python manage.py schedule herfy
python manage.py schedule hungerstation
```

Official-source collectors preserve their existing options:

```bash
python manage.py collect kfc --channel=PICKUP
python manage.py collect hardees --channel=DELIVERY --no-screenshots
```

HungerStation collects every configured restaurant by default. Its source
options remain available, including the ADB serial configured by
`HUNGERSTATION_ADB_SERIAL` in `.env`:

```bash
python manage.py collect hungerstation --brand kfc
python manage.py collect hungerstation --all --serial emulator-5554
python manage.py collect hungerstation --brand herfy --from-capture capture.xml
```

Run `python manage.py --help` or a command's `--help` for the dispatcher
summary. Source-specific parsing remains in the real collector modules.

## Application behavior

The React application provides market overview, menus, promotions, price
changes, history, Product Matching, manual collection controls, and Excel
export. The export is served by FastAPI at `/api/v1/market/export.xlsx` and is
linked from Market Overview.

The Market Overview pull starts KUDU and the four official-source competitors
concurrently. It collects both channels without event screenshots, retries one
failed or incomplete pass, and keeps previous complete snapshots available
when an upstream source fails. Progress logs are generated under
`bff/data/pull_logs/` and are not committed.

To refresh only KUDU, set `KUDU_API_USERNAME` and `KUDU_API_PASSWORD` in `.env`
and run:

```bash
python -m kudu.refresh
```

## Architecture

```text
frontend/                    React application
bff/                         FastAPI routes and application services
adapters/                    Shared BFF contract adapters
competitors/shared/          Shared collector/backend infrastructure
competitors/<brand>/         Source-specific collectors, data, and tests
kudu/                        KUDU catalog refresh and baseline data
docs/PROJECT_PLAN.md         Product and frontend plan
manage.py                    Single local and operational entry point
```

The four official-source adapters inherit directly from
`SQLiteMonitorAdapter`. Shared competitor code covers data models, payload
validation, change detection, SQLite schema/binding, CLI running, and daily
scheduling. Each brand keeps its own configuration, API/client behavior,
normalization, offer parsing, option extraction, and ingestion details.

The BFF is the composition boundary. React never reads source databases or
imports restaurant backend modules. Each collector writes only to its own data,
log, image, export, and SQLite locations.

See the source documentation for operational details:

- [KFC](competitors/kfc/README.md)
- [Hardee's](competitors/hardees/README.md)
- [Burger King](competitors/burger_king/README.md)
- [Herfy](competitors/herfy/README.md)
- [HungerStation](competitors/hungerstation/README.md)
- [Product/frontend plan](docs/PROJECT_PLAN.md)

## Test

```bash
python -m compileall -q adapters bff competitors kudu
python -m pytest -q
npm test
npm run build
git diff --check
```

## Data safety

Generated raw data, screenshots, logs, exports, databases, WAL/SHM files, and
local environment values must not be committed as cleanup work. The tracked
HungerStation database/images and `kudu/data/catalog.json` are operational data;
do not replace, format, or delete them during code maintenance.

Collectors do not perform login, OTP, payment, or checkout actions. Consult
each implemented source README for its source-specific security and collection
constraints.
