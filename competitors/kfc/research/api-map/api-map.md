# KFC Saudi (`saudi.kfc.me`) API map

**Last verification date: 2026-08-05.** Machine-readable version:
[`api-map.json`](api-map.json) - `collector/api-client.js` and
`backend/schema_validator.py` both read from that file's shapes (informally;
the JSON is the source of truth documentation, not something the code
`require()`s at runtime, so a future edit here doesn't silently change
behavior without also touching the client).

All endpoints below are **public, first-party, unauthenticated (guest
session) endpoints** that the site's own browser frontend calls for every
anonymous visitor. Nothing here requires login, an OTP, a phone number, or
payment details. No cookie/token/device-id value is ever written to this
file, to git, or to any log - see "What is never recorded" at the bottom.

## How this was verified

1. Read the project's existing HAR capture (`legacy/kfc-saudi-complete-flow.har`)
   and its existing crawler code (`legacy/*.js`), which had already
   identified `validateLocation`, `getStoreList`, `getMenuConfig`, `getMenu`
   as real endpoints from a prior live session.
2. Ran a fresh, live, low-volume Playwright session against
   `https://saudi.kfc.me/en/home` on 2026-08-05 and re-confirmed `guestLogin`,
   `getAppConfig`, `getStoreList`, `getMenuConfig` (`PICKUP`, with and
   without `storeId`), `getMenu`, `getHome`, `validateLocation` all return
   `200` with the shapes below, and discovered `getNewStore` (not previously
   documented anywhere) as the endpoint the Self-Pickup "USE MY LOCATION"
   button calls.
3. Downloaded the site's own production JavaScript bundles and located the
   literal endpoint-definition table (`{method:"POST", path:"/api/..."}`)
   plus the request-thunk implementation for `getProductsByCategory` and
   `getProgressivePromotion` - confirming their path, HTTP method, and a
   *candidate* request payload shape from their payload-assembly code.
4. Built the collector end to end against that candidate shape and ran it
   live (`node collector/collect.js --run-id=... --channel=PICKUP`) against
   the fixed branch. This surfaced two real corrections the static bundle
   analysis alone did not catch:
   - the site's edge WAF (Azure Application Gateway) 403s any direct HTTPS
     request missing browser-shaped `user-agent`/`origin`/`referer` headers,
     even with valid cookies/deviceid - fixed by adding them as static
     defaults in `collector/config.js`;
   - `getProductsByCategory`'s response nests `products` ONE level under
     `data`, not two (`response.data.products`, not
     `response.data.data.products`) - the bundle's own
     `u?.data?.data?.products` optional-chaining was unwrapping an axios
     envelope one level above the JSON body actually inspected here.
   After both fixes, a full live run against all 12 real categories of the
   fixed branch succeeded end to end - see each endpoint's verification
   note below for the exact confirmed shapes.

## Branch selection update (2026-08-06)

The fixed branch was changed from **SITEEN / storeId=251** to **RABWAH /
storeId=223** (still Riyadh). At this verification time SITEEN was closed
for Pickup - `getNewStore` no longer resolved it as the nearest branch for
the configured coordinates, a normal operating-hours state (see
`channel-collector.js`'s `verifyBranchExists` note), not a fault - so a
branch with both channels currently active was chosen instead:

1. Queried `getStoreList`'s full Riyadh directory (98 stores).
2. Filtered to stores with `services.tak=1` AND `services.del=1` AND
   `active=1` AND `cmsStatus=1` - 9 candidates.
3. Live-checked each candidate via `getNewStore` (Pickup) and
   `validateLocation` (Delivery) using that store's own coordinates - 8 of
   9 resolved correctly on **both** channels (the 9th, storeId=817 "KFC KSA
   Lab", is a non-Riyadh test/lab store with out-of-range coordinates and
   failed `validateLocation` with `409 not deliverable`).
4. Ran a full `getMenuConfig -> getMenu -> getProductsByCategory` check for
   the top 3 candidates on **both** channels. **RABWAH/223** returned 12
   categories and identical real priced products on both channels (e.g.
   `"Double Up Deal"` `originalPrice=63` / `specialPrice=42`, `"Super Mega
   Deal"` `originalPrice=125` / `specialPrice=75`) and was selected.

The other 7 branches the same check found eligible - DAAERY/128,
EUROMARCHE/143, HAMZA/165, SOLY/253, OM ELHAMAM/210, NOZHA/206,
INDUSTRIAL/171 - would also satisfy the "both channels have prices"
requirement; RABWAH was simply first and is now the default in
`.env.example`, `collector/config.js`, and `backend/config.py`.

The endpoint shapes documented below are branch-independent (they take
`storeId`/`lat`/`lng` as plain payload fields, not something tied to one
specific branch) and were not expected to, and did not, change for
RABWAH - so the `verificationNote` values quoted below that mention
storeId=251/SITEEN are left as-is: they are a historical record of what
was literally observed on 2026-08-05, not a claim about the currently
configured branch.

## Endpoints

### `POST /api/guestLogin`
Anonymous guest-session bootstrap. Fired automatically by the site itself on
every page load; not something this system chooses to do beyond letting the
page load. No credentials involved (`isGuest: 1`, empty `phnNo`/`email`).

- **Channel dependency:** none. **Branch dependency:** none.
- **Used for:** establishing the session headers/cookies every other call needs.

### `GET /api/getAppConfig`
Global config, most importantly a blob-storage SAS token
(`data.blobBaseUrl.SASToken`) and base path (`data.blobBaseUrl.jsonBase`)
that `getStoreList`, `getMenu`, and (reconstructed) `getProductsByCategory`
all expect as `subPath` / `path` payload fields.

- **Used for:** `subPath`/`path` values on downstream calls.

### `POST /api/getStoreList`
```json
{"payload":{"path":"<jsonBase>","country":"ksa","subPath":"<SASToken>"}}
```
Returns **every** city and branch in Saudi Arabia:
`data[] = {cityId, cityName, name_en, store:[{storeId, name_en, name_ar,
active, cmsStatus, services:{del,tak,din,driveThru,carHop}, location:
{latitude,longitude}, address_en, address_ar, menuTempId}]}`.

- **Used for:** the branch-verification check run at the start of *every*
  collection run - confirms `KFC_STORE_ID` still appears under `KFC_CITY`
  with `active=1`. If not, the run is marked `FAILED` immediately (see
  README "Branch verification").

### `POST /api/validateLocation`
```json
{"lat": 24.6866, "lng": 46.724, "screen": "LOCATION", "addressSubType": "DELIVERY"}
```
Resolves DELIVERY serviceability for a coordinate. `200` + `data.store` when
deliverable; `400`/`409` + a human-readable `message` when not.

- **Channel dependency:** `DELIVERY`.
- **Used for:** confirming the fixed branch still serves the configured
  coordinates for delivery, once per Delivery run.

### `POST /api/getNewStore` — *newly documented, not previously known*
```json
{"lat": 24.6866, "lng": 46.724}
```
Response: `{"data": {"cityId": 11, "areaId": 8157, "storeId": 251}}`.
This is what the Self-Pickup flow's **USE MY LOCATION** button calls -
resolves the nearest pickup-capable branch for a coordinate. Live-confirmed
on 2026-08-05: our configured coordinates resolve to `storeId: 251`
(**SITEEN**), matching `KFC_STORE_ID`.

- **Channel dependency:** `PICKUP`.
- **Used for:** confirming the fixed branch is still the nearest branch to
  the configured coordinates, once per Pickup run.

### `POST /api/getMenuConfig`
```json
{"orderType": "PICKUP", "storeId": 251}
```
(`storeId` is included once a specific pickup branch is known; live-confirmed
both with and without it. For `DELIVERY`, no `storeId` field is sent - the
branch context comes from the session's last-validated address.)

Response: `{"data": {"expiryTime": 1785974340, "menuConfigId": "KFC_SA_76",
"clusterId": "14_5"}}`.

- **This is the call that fixes the channel for everything downstream.**
  Per the task spec, the collector never infers channel from a `service`
  field buried inside a later response - it tags every category/product
  it collects with whichever channel (`PICKUP` or `DELIVERY`) started this
  particular `getMenuConfig → getMenu → getProductsByCategory` chain.
- **Used for:** `menuConfigId` + `clusterId`, required by every call below.

### `POST /api/getMenu`
```json
{"payload": {"path": "", "brand": "kfc", "country": "ksa", "defMenu": 1,
  "menu": 5, "locale": "En", "service": "DELIVERY", "menuConfigId": "KFC_SA_76",
  "subPath": "<SASToken>"}}
```
Response: `{"data": {"categories": [{"id": 1710, "name": "Burgers",
"parentId": 0, "level": 3, "productCount": 19, ...}], "tags": [...]}}`.
Live-confirmed: 12 categories for our branch (Exclusive, Baloot Limited
Edition, New! Hot Honey, Matchday Boxes, Deal of the Day, Chicken Meals,
Wraps, Burgers, Chicken Buckets, Sides, Dips, Drinks).

- **Category objects carry a product *count*, never the products
  themselves.** `getProductsByCategory` must be called once per category id.
- **Used for:** the category list the collector loops over.

### `POST /api/getProductsByCategory` — live-verified end to end
```json
{"id": 1710, "cluster": "14_5", "configId": "KFC_SA_76", "path": "",
  "brand": "kfc", "country": "ksa", "locale": "En", "service": "PICKUP",
  "menu": 5, "subPath": "<SASToken>"}
```
Response: `{"data": {"id": 1710, "name": "Burgers", "promoId": 0,
"services": {...}, "products": [{"id": 18182, "sku": 1319, "name":
"Double Up Deal", "description": "...", "originalPrice": 63,
"specialPrice": 42, "disPercentage": "33% OFF", "promoId": 9583,
"limited_offer": 0, "typeId": "bundle", "bundleTypeId": "bundle",
"assets": [{"src": "https://.../1319-combo.png"}], "variants": [],
"steps": [{"id": 1, "title": "Choice of Sandwich", "type": "radio",
"minimum": 1, "maximum": 1, ...}], "subOptionStr": "Zinger
Sandwich,Lettuce,...", "subOptionStrAr": "زنجر ساندويتش..."}]}}`.

**This is the primary product + price + offer data source for the whole
system.** Live-verified against all 12 real categories of the fixed branch.
Two things worth calling out explicitly:

- **`specialPrice`'s "not a simple fixed-discount price" sentinel is `0`.**
  Live-confirmed: ~28/106 sampled products - all build-your-own
  "Combo"/"Box" bundle upsells with a real positive `promoId` but an
  *empty* `disPercentage` - carried `specialPrice=0` alongside a real,
  non-trivial `originalPrice` (e.g. 19 SAR). A genuine free $19 combo is
  not plausible; `backend/normalizer.normalize_special_price()` treats any
  value `<= 0` (and any value `>= originalPrice`) as "no special price".
- **`promoId`'s "no active offer" sentinel is `-1`, not `0`.** Live-confirmed
  across 106 sampled products: 37 carried `promoId=-1` with no discount at
  all, every other product carried a distinct positive integer alongside a
  real `specialPrice`. (The category object's own top-level `promoId` uses
  `0` as its sentinel instead - a different field on a different object;
  don't conflate the two.) `backend/normalizer.normalize_promo_id()` treats
  any value `<= 0` as "no promo".
- **The response's `data` field is the category object itself, with
  `products` as a direct inline array** (`response.data.products`) - a
  correction versus the compiled bundle's own optional-chaining code, which
  suggested one more level of `.data` nesting (see "How this was verified"
  above). `collector/api-client.js` uses the corrected path.
- **Size is carried in `variants[].options[]`** (`{id, title: "Regular" |
  "Medium" | "Large", isSelected}`), present only on products that actually
  have a size choice - absent entirely otherwise. This is the field the
  Excel "Legacy View" sheet's Regular/Medium/Large columns read; if a
  product has no `variants` entry, those columns are left blank rather than
  guessed (per spec).
- **No calorie field exists anywhere in this response** - `nutrition_facts`
  was an empty array on every one of the ~120 products sampled live.
  `calories` is stored as `NULL`, never guessed.
- **`locale: "Ar"` returns HTTP 404** ("Upstream returned 404") on this
  endpoint - swapping the locale field alone is not sufficient for Arabic
  content (see `api-map.json`'s `localeNote` on this endpoint for the
  working theory). `product_name_ar` / `description_ar` /
  `category_name_ar` are stored as `NULL` in v1 as a result - this is the
  one required field group this system does **not** currently populate;
  see the root README "What could not be verified".
- `collector/api-client.js` validates the response shape on every call; a
  mismatch marks that category (and, if every category fails, the whole
  channel run) `PARTIAL`/`FAILED` rather than fabricating product data -
  see "Schema validation" below.

### `POST /api/getHome`
```json
{"path": "", "country": "ksa", "defMenu": 1, "defTemp": 5, "cluster": "14_5",
  "locale": "En", "subPath": "<SASToken>", "menuConfigId": "KFC_SA_76"}
```
Homepage banner/deal-rail content. The collector calls this for exactly one
reason: its response includes `data.menuId` (a numeric id not present
anywhere in `getMenu`'s response), which `getProgressivePromotion`'s
payload needs. No product/price/offer data is ever read from here.

- **Used for:** `menuId`, passed through to `getProgressivePromotion`. A
  failure here is logged and `getProgressivePromotion` is skipped for that
  run - it never affects the channel's `crawl_runs` status.

### `POST /api/getProgressivePromotion` — live-verified end to end
```json
{"orderType": "PICKUP", "menuId": 14, "menuTempId": 5, "curMenuId": 14,
  "curMenuTemplateId": 5, "cluster": "14_5", "configId": "KFC_SA_76"}
```
Response: `{"data": {"parentPromo": {}, "promolist": {}, "headerText":
"Special offers for you"}}`.

- **`data` is an object with a `promolist` map keyed by promoId - not a
  bare array** as the initial bundle-based reconstruction assumed.
  `collector/channel-collector.js` extracts `Object.values(data.promolist)`
  defensively. `promolist` was empty at verification time (no progressive
  promotion was running on the fixed branch that day) - the shape of a
  *populated* entry was not observed live; see the root README "What could
  not be verified".
- **Used for:** supplementary, tiered/progressive promotions not tied to a
  single product/category. Treated as best-effort - a failure here never
  fails the run on its own, since `getProductsByCategory` already carries
  the primary, always-required offer fields (`specialPrice`, `promoId`,
  `limited_offer`, `disPercentage`, `subOptionStr`) per product.

## Endpoints observed but not used

| Endpoint | Why not used |
|---|---|
| `GET /api/profile` | Guest profile echo (device id, cart id). No product/price data. |
| `POST /api/kfcloyalty/auth`, `POST /api/kfcloyalty/loyalty-config`, `GET /api/amr-loyalty/config` | Walaa loyalty program surface. Fires automatically on page load; we read nothing from it. Out of scope (no login, no loyalty points). |

## Schema validation

Every response is checked against its minimal expected shape (HTTP `200`,
expected top-level keys present, expected array fields are actually arrays)
before any value from it is used - see `backend/schema_validator.py` and
`collector/api-client.js`'s `validateResponse()`. On a mismatch:

1. The endpoint name, HTTP status, and raw response body are saved to
   `data/raw/<run_id>/schema-errors.json`.
2. The affected category is marked failed for that run.
3. If **any** category failed, the channel's `crawl_runs` row becomes
   `PARTIAL`; if **all** categories failed (or the branch-verification step
   itself failed), it becomes `FAILED`.
4. `PARTIAL`/`FAILED` runs are **excluded from change detection** entirely
   (`backend/change_detector.py` only ever compares two `SUCCESS` runs) -
   this is what prevents an API schema change from ever generating a false
   `PRODUCT_REMOVED`/`OFFER_ENDED` event.

## What is never recorded here (or anywhere in git)

- `cookie` / `Set-Cookie`
- `authorization` (bearer token, if/when present)
- `refreshtoken`
- `deviceid` values (the *header name* is documented; the *value* is
  generated per-run by the guest-session bootstrap and never persisted
  beyond the run that created it)
- Any request/response captured live during verification was inspected with
  these fields redacted before being written into this document.
