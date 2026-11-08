# KUDU Price Benchmark

Internal price and promotion monitoring for KUDU Marketing. React is the only
frontend, and FastAPI is the application backend.

```text
Browser → React → FastAPI BFF → adapters → source databases/catalogs
```

## Sources

| Source | Collection path |
| --- | --- |
| KUDU | KUDU API/catalog baseline; HungerStation menu from the KUDU integration API |
| KFC | Official-source collector |
| Hardee's | Official-source collector |
| Burger King | Official-source collector |
| Herfy | Official-source collector |
| AlBaik | Official ALBAIK Android app: Arubah pickup and nearby delivery, plus HungerStation |
| HungerStation | Android Emulator through ADB |

McDonald's currently has HungerStation data only. The independent **Albaik App
Collection** panel in Market Overview runs both official app channels and shows
each result. See [AlBaik setup and collection](competitors/albaik/README.md).

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
python manage.py collect albaik-app --channel PICKUP
python manage.py collect albaik-app --channel DELIVERY

python manage.py schedule kfc
python manage.py schedule hardees
python manage.py schedule burger-king
python manage.py schedule herfy
python manage.py schedule hungerstation
```

### Automatic collection

Set `AUTO_PULL_TIMES` in `.env` (Riyadh time, comma-separated) and restart
the API, for example:

```bash
AUTO_PULL_TIMES=11:00
```

At each time the API runs the website collection and, when it finishes, the
HungerStation collection (`AUTO_PULL_HUNGERSTATION=false` skips it), then the
official Albaik app, pickup followed by delivery (`AUTO_PULL_ALBAIK_APP=false`
skips it). Each collection waits for the previous group to finish. Runs
appear on Market Overview with the same progress table as the buttons, and
the page shows the schedule and the next run. Use one API process (no
`--workers`), or each process would start its own schedule. The per-brand
`manage.py schedule` commands are not needed alongside it.

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

Each restaurant's Menu offers an **All channels** comparison with one product
per row and separate Pickup, Delivery and HungerStation prices. The BFF menu
endpoint (`/api/v1/brands/{brand_id}/menu`) groups the complete menu before
search and pagination, using shared source IDs or unambiguous normalized
English/Arabic names. Different sizes, quantities and meal variants are kept
separate when matching names; uncertain matches remain separate rows. Missing
prices stay unknown, and discounts, sizes and availability remain specific to
each channel. All menus place main dishes first, followed by sides and
desserts, then sauces and drinks.

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

KUDU products appearing in several menus are stored once per channel, keeping
their existing `<channel>-<itemId>` identity. The canonical record comes from a
regular menu before Special Offers, then the lexicographically smallest menu ID
if several menus have equal priority. Its image, description and pricing fields
stay together; other occurrences are retained in `categoryVariants`. Those
memberships keep products discoverable under Special Offers without increasing
product counts or creating new matching IDs. Promotions use the canonical
product's price and image and do not imply a discount.

Duplicate occurrences must agree on base price. Pickup must also agree on
whether default sides are added and on each applied drink/fries price (missing
or null sides count as zero). Delivery uses its inclusive base price, so differing
side settings are retained but not added. Numeric strings compare numerically.
Ambiguous pricing, conflicting records within one menu, incomplete collections
and failed writes keep the previous snapshot. Collection status includes the
reason via `KUDU_ERROR`, without credentials or response bodies.

KUDU's own HungerStation menu comes from the KUDU integration API, not the
emulator. Set `KUDU_AGGREGATOR_TOKEN` in `.env` and run:

```bash
python manage.py collect kudu-hungerstation
```

It also runs first in "Collect HungerStation". The integration host is on
KUDU's internal network, so the machine running it must reach that network.
The API has no images: items reuse the main-menu image of the same item id,
the same name, or a clearly matching name, and stay blank otherwise.

## AI mapping

The AI page suggests, for one KUDU item, the closest item at each competitor
in the same channel, following the matching rules agreed with Marketing
(same kind of item and protein, meal versus sandwich, patty and piece counts,
Medium on HungerStation and Regular elsewhere, no temporary promo bundles).
The model sees names and descriptions only, never prices. Suggestions are
reviewed on the page and saved as normal Playground mappings. It needs
`ANTHROPIC_API_KEY` in `.env`; `AI_MODEL` (default `claude-opus-5-5`) and
`AI_EFFORT` are optional. Spend estimates are logged in `bff/data/ai.db`.

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
node --test competitors/burger_king/tests/*.js competitors/kfc/tests/*.js
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
