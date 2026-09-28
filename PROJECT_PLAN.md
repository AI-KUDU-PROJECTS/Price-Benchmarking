# Kudu Price Benchmark — Product and Frontend Plan

## Purpose

Build a new unified React frontend that turns the existing competitor data into a clear pricing-intelligence product for the marketing team.

The current restaurant collectors, databases, schedulers, normalization logic, and change-detection logic remain independent. The new work adds a thin BFF, one adapter per restaurant, and a shared presentation layer. It does not merge or rewrite the restaurant backends.

Streamlit dashboards remain the operations surface (Run Now, logs, Excel export). The React app is the marketing product.

## Current Implementation Scope

**Scope update (2026-09-27):** KUDU production menu ingestion is now implemented as the first, baseline brand. Delivery and pickup item names, prices, images, and publish flags are loaded through a dedicated snapshot adapter. Cross-brand product matching and price positioning remain deferred.

The first release covers four competitors in this exact order:

1. KFC
2. Hardee's
3. Burger King
4. Herfy

The product answers three immediate questions:

- What changed in the market?
- Which changes require attention?
- What promotions are competitors currently running?

All four brands are connected through independent adapters and share the same BFF contract and React workspaces. KFC remains the reference implementation for future component changes.

## Implemented Integration

The current implementation follows this path for every connected brand:

```text
KFC / Hardee's / Burger King / Herfy SQLite
   ↓
Independent Adapter per brand
   ↓
Shared BFF API
   ↓
Shared React workspaces and market pages
```

Integration rules:

- React never opens a restaurant database or imports restaurant backend modules.
- Each restaurant adapter is the only code that knows that restaurant's tables, keys, and field names.
- The BFF is the only HTTP surface the frontend calls. One base URL, versioned contract.
- Market Overview, Market Changes, and Promotions aggregate all connected brands while preserving each brand's source context.
- Product History is a first-class page reached from menu, changes, and promotions — not an optional extra.

## Navigation and Information Architecture

Keep a persistent left sidebar with the following order:

```text
KUDU
PRICE BENCHMARK

BASELINE
  KUDU Menu

OVERVIEW
  Market Overview
  Market Changes
  Promotions

COMPETITORS
  KFC
  Hardee's
  Burger King
  Herfy
```

Each competitor entry opens an independent brand workspace using the same shared page patterns:

- Overview
- Menu
- Promotions
- Changes
- History

The sidebar should always preserve the competitor order above. Brand-specific pages may use tabs or secondary navigation without duplicating the main sidebar.

Market Overview, Market Changes, Promotions, and every connected brand workspace are real routes backed by the shared BFF contract.

## Product Architecture

```text
KFC SQLite ── KFC Adapter ────────┐
Hardee's SQLite ── Hardee's Adapter ┤
Burger King SQLite ── BK Adapter ──┼── BFF API ── React
Herfy SQLite ── Herfy Adapter ─────┘
```

All four branches are connected. Future competitors add an adapter and brand configuration; they do not add new page implementations.

### Backend boundaries

Keep each restaurant's implementation independent under its existing module/file structure. Each module owns its own:

- scraper or collector;
- raw and normalized data;
- database;
- scheduler and run status;
- price and promotion extraction;
- change-detection logic;
- tests and restaurant-specific edge cases.

Do not move restaurant-specific logic into the React frontend. Do not create one combined scraper or one combined restaurant database as part of this plan.

### Adapter boundary

Each adapter maps one restaurant's existing SQLite output into the shared contract. It:

- normalizes field names and response shape;
- preserves source values, including unknown/null;
- does not invent prices, discounts, or ended/removed status;
- exposes brand capabilities (`hasDiscount`, `hasSizePrices`, `hasImages`, channels);
- keeps product identity stable, including `channel` and source key.

The adapter may read that restaurant's database. Nothing else may.

### BFF boundary

The BFF is a thin composition layer:

- serves `/api/v1/...` from the shared contract;
- calls one or more adapters;
- attaches freshness and source-run context to every response;
- aggregates Market Overview from whatever adapters are connected;
- does not contain KFC/Hardee's/BK/Herfy parsing, SQL, or collector knowledge.

The frontend consumes only this BFF. It should not read restaurant databases or know how an individual scraper works.

## Guiding Principles

1. Preserve working collectors and backend isolation.
2. Unify presentation and contracts, not restaurant-specific extraction logic.
3. Complete the KFC slice as the reference implementation before any other brand adapter.
4. Reuse shared components and layouts for the other brands; use brand configuration only for labels, colors, logos, and supported features.
5. Show missing or unavailable values honestly. Never convert a missing price into zero or infer a discount that the source does not provide.
6. Include source channel, location, and collection timestamp where they affect interpretation.
7. Prefer a focused first release over a generic platform or premature abstraction.
8. Keep the market-level pages useful even when one brand is stale, unavailable, or partially populated.
9. Make drill-down paths predictable: market summary → event or promotion → brand/product detail → history.
10. Treat the unified contract as versioned and testable so backend changes do not silently break the frontend.
11. Do not collapse `not_observed` into `removed` or `ended`. The source distinction stays in the contract; the UI may group them for scanning.
12. Collection is one verified Riyadh branch per brand. Location context must not look national.

## Delivery Phases

> **Current delivery status (2026-09-14):** Phases 1–4 are implemented for KFC, Hardee's, Burger King, and Herfy. The shared Market Changes feed and Promotions monitor are also live across the four connected brands. The phase descriptions below retain KFC as the reference implementation sequence; they are not a statement that the other three brands are disconnected.

### Phase 1 — React Foundation

Create the frontend shell without changing the existing restaurant logic.

Deliverables:

- React application foundation;
- persistent left sidebar in the agreed order;
- application routing for the first-slice pages;
- shared layout, page header, cards, tables, badges, filters, empty states, loading states, and error states;
- small design system with typography, spacing, color tokens, and status semantics;
- API client with one base URL, typed responses, and consistent error handling;
- desktop-first responsive layout;
- real routes for Market Changes, market Promotions, and all four connected brand workspaces.

Exit criteria:

- all first-slice routes are navigable;
- the sidebar and layout remain consistent across pages;
- pages can render loading, empty, success, stale-data, disconnected, and error states using mock data.

### Phase 2 — Contract, KFC Adapter, and BFF

Define the smallest shared contract needed by the first slice and connect KFC SQLite to the BFF.

Deliverables:

- shared types for brand, collection run, product, product size, promotion, change event, and brand capabilities;
- KFC adapter that maps existing KFC SQLite data into that contract;
- BFF endpoints needed by Market Overview and the KFC pages;
- stable identifiers (brand + channel + source id) and timestamps in `Asia/Riyadh`;
- contract validation and representative fixtures;
- clear handling for missing price, missing/expired image, stale run, unavailable channel, and partial data.

Exit criteria:

- BFF responses for KFC can be consumed without any KFC-specific parsing in the client;
- adapter tests cover missing price, pickup vs delivery, size prices, not-observed vs removed, and stale runs;
- no KFC database access exists outside the KFC adapter.

### Phase 3 — First Product Slice (KFC)

Ship the six screens against live BFF data.

**Market Overview** (KFC-backed):

- market last-updated timestamp from connected brands only;
- brand health and freshness, with disconnected brands marked as such;
- price decreases, price increases, new products, new offers, ended offers;
- prioritized highlights from supported facts, each linking to the relevant change, promotion, product, or brand page;
- brand status table with last successful update, freshness, product count, promotion count, change count, and error/partial-data/disconnected state.

Highlight ranking for the first slice, in order:

1. new offer;
2. price decrease;
3. offer ended;
4. new product;
5. price increase;
6. product/offer returned;
7. availability change.

Do not promote `not_observed` events into this list until the third consecutive miss has become `removed` or `ended`.

**KFC Overview:** last successful update, run health by channel, item count, active promotions, recent changes, and key highlights.

**KFC Menu:** searchable/filterable product list with category, channel, current price, previous price when available, size prices when available, image, and last-seen time.

**KFC Changes:** price, product, and promotion events with before/after values and drill-down to product history or promotion detail. Keep `not_observed` distinct from `removed` / `ended`.

**KFC Promotions:** visual cards with image, current/regular price, discount when valid, status, and first/last-seen dates. Use a deliberate missing-image state; never a broken image.

**Product History:** per-product observations over time from menu, change, or promotion drill-down, without cross-brand comparison.

Exit criteria:

- a marketer can complete a daily KFC check-in from Market Overview without opening Streamlit;
- every highlight and change row opens the underlying product or promotion history;
- incomplete fields, especially prices or promotions, are visibly marked rather than guessed;
- a disconnected brand does not make Market Overview look fully updated.

### Phase 4 — Brand Reuse

After the KFC slice is accepted, add one adapter and brand configuration at a time:

1. Hardee's
2. Burger King
3. Herfy

Each additional brand should require a backend adapter and brand configuration, not a copy of the frontend pages. Brand-specific differences must be explicit capabilities or data-availability states (for example, Burger King has no discount field; offers are category-detected).

Exit criteria:

- all four competitors use the same user experience and unified contract;
- each restaurant backend remains independently runnable and maintainable;
- Market Overview composes connected brands without a shared restaurant database.

### Phase 5 — Unified Market Changes

Create one chronological feed across the connected competitors.

Required event types in the contract (do not collapse):

- `price_increased`, `price_decreased`;
- `product_added`, `product_removed`, `product_not_observed`, `product_returned`;
- `offer_started`, `offer_ended`, `offer_not_observed`, `offer_returned`;
- `availability_changed` when reliably detected;
- other source events (`new_in_channel`, `regular_price_changed`, `special_price_changed`, `details_changed`, `category_changed`) remain available for brand Changes pages.

Required filters:

- brand;
- event type;
- date range;
- category;
- channel, when available.

Each row/card should show the brand, product, event, before/after values, percentage change when valid, timestamp, and data source context. Drill-down should open the related brand/product history or promotion detail.

Exit criteria:

- users can isolate important changes quickly and verify the underlying detail;
- filters are reflected in the URL so filtered views can be revisited or shared internally.

### Phase 6 — Visual Promotions Monitor

Create a visual monitor focused on competitor campaign activity.

Required content:

- product image when available;
- brand and product/offer name;
- current price and regular price when known;
- valid discount amount/percentage when derivable;
- active, new, or ended status;
- first-seen and last-seen dates;
- channel and category context.

Required filters:

- brand;
- promotion status;
- date range;
- category;
- channel, when available.

Use a card/gallery presentation with a detail view. Supply a deliberate missing-image state; do not use broken image placeholders. Treat expired source image URLs as missing, not as broken.

Exit criteria:

- users can visually scan current and recently ended competitor offers;
- selecting a promotion reveals its observed history and source details.

## Frontend Routes

```text
/overview
/changes
/promotions

/competitors/kfc
/competitors/kfc/menu
/competitors/kfc/promotions
/competitors/kfc/changes
/competitors/kfc/history
/competitors/kfc/products/:productId
/competitors/kfc/promotions/:promotionId

/changes/:changeId
```

Later brands reuse the same pattern:

```text
/competitors/:brand
/competitors/:brand/menu
/competitors/:brand/promotions
/competitors/:brand/changes
/competitors/:brand/history
/competitors/:brand/products/:productId
/competitors/:brand/promotions/:promotionId
```

Product, promotion, and change detail routes are required. History without a `productId` is a filtered index; the canonical history view is `/competitors/:brand/products/:productId`.

## BFF API Shape

```text
GET /api/v1/market/overview
GET /api/v1/market/changes?brand=kfc&type=price_decrease&from=...&to=...
GET /api/v1/market/promotions?brand=kfc&status=active

GET /api/v1/brands
GET /api/v1/brands/:brand/overview
GET /api/v1/brands/:brand/products
GET /api/v1/brands/:brand/products/:productId
GET /api/v1/brands/:brand/products/:productId/history
GET /api/v1/brands/:brand/promotions
GET /api/v1/brands/:brand/promotions/:promotionId
GET /api/v1/brands/:brand/changes
GET /api/v1/changes/:changeId
```

First-slice BFF implements Market Overview plus the KFC brand endpoints. Market Changes and market Promotions endpoints may return an empty connected set until Phases 5 and 6.

## Shared Contract

Minimum shared concepts:

```text
Brand
  id, name, health, lastSuccessfulRunAt, dataFreshness,
  capabilities, channels, locationLabel

BrandCapabilities
  hasDiscount, hasSizePrices, hasImages

Product
  id, brandId, sourceId, nameAr, nameEn, category, imageUrl,
  channel, location, regularPrice, specialPrice, currency,
  sizes[], availability, firstSeenAt, lastSeenAt, observedAt,
  sourceRunId

ProductSize
  label, price, currency

Promotion
  id, brandId, productId, title, imageUrl, status,
  regularPrice, promotionalPrice, discountPercent,
  firstSeenAt, lastSeenAt, channel, source

ChangeEvent
  id, brandId, productId, promotionId, type,
  beforeValue, afterValue, percentageChange,
  detectedAt, channel, location, sourceRunId

CollectionRun
  id, brandId, status, startedAt, completedAt,
  channel, location, itemCount, warningCount, errorSummary

ProductHistory
  product, observations[]
```

Contract rules:

- timestamps use `Asia/Riyadh` in one documented format;
- money is represented consistently and includes currency;
- nullable means unknown/unavailable, never zero;
- event types and health states use controlled values;
- `not_observed` is not the same as `removed` or `ended`;
- pickup and delivery are separate product identities when the source treats them as such;
- responses include freshness and source-run context;
- pagination/filter metadata is consistent for list endpoints.

## Future Scope — Not Part of the Current Implementation

The following items are explicitly deferred and should not block or expand Phases 1–6:

- cross-brand **Market Comparison**;
- Kudu-versus-market positioning;
- unified product classification across brands;
- product matching/equivalency between brands;
- automated alerts or notifications;
- long-term market trends, price indices, and advanced analytics;
- replacing Streamlit as the operations surface.

These features require additional product decisions and, especially for comparison, a trusted classification and product-matching model. The current architecture should avoid preventing them, but no implementation should be added yet.

## Definition of Done

### First slice

- KFC SQLite → KFC Adapter → BFF API → React is the only data path;
- Market Overview, KFC Overview, KFC Menu, KFC Changes, KFC Promotions, and Product History work against live KFC data;
- disconnected brands are explicit;
- missing, stale, partial, and failed data states are explicit;
- Streamlit and the KFC collector remain independently runnable.

### Current plan

- the new React frontend exposes the agreed sidebar and routes;
- KFC, Hardee's, Burger King, and Herfy appear in the exact agreed order;
- all four independent backends feed the frontend through adapters and the BFF;
- KFC is implemented and accepted as the reference before the other brand integrations;
- Market Overview, Market Changes, and Promotions Monitor meet their phase exit criteria;
- no future-scope cross-brand comparison, matching, alerts, or long-term trend work is included.
