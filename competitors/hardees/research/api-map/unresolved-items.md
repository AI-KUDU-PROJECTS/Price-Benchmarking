# Unresolved items

Everything below was actively investigated but not conclusively verified.
Nothing in `api-map.json`/`api-map.md`/`field-map.json` presents any of
these as confirmed - each is marked `not_observed`, `inferred_unresolved`,
or an explicit `verificationTier` note at its source. Listed here as a
single checklist for whoever picks this up next.

> **2026-08-06, second research session - status change summary:**
> item **#1 (hidden modifier groups) is now RESOLVED** and item **#9
> (channel differences on another branch) is substantially addressed**
> (re-tested on a second, distant branch with identical results - a real
> difference remains theoretically possible on an untested third branch
> or at the cart/fee level, so it is not marked fully closed). Item #5 is
> partially resolved (two of its three endpoints). A new sub-question was
> added to item #7 (`prepTime`/`promiseTime` possibly being constants).
> Items #2, #3, #4, #6, #8, #10, #11 are unchanged from the first session.
>
> **2026-08-07, Streamlit-integration session - additional changes:**
> item #1's nested-item-id rule was **corrected** (a live smoke test
> while wiring the Streamlit preview caught a documentation error -
> `selectedItem` is a sku, not an id; see item #1's correction note).
> Item **#5's `getPromotion` sub-item now has strong evidence of being
> dead/unreachable frontend code**, not just an untried payload (see its
> updated write-up). Item **#12 (request-volume/rate-pacing strategy) is
> new**, addressed with concrete numbers from a live catalog count.

## 1. Hidden modifier groups (sauces / add-ons / sides for a specific product) - **RESOLVED 2026-08-06 (second research session)**

~~`getProductsByCategory`'s `products[].steps[]` entries carry only
`{title, subtitle, type, minimum, maximum, isTopping, id, compId,
groupId}` - no nested options list.~~ This is still true of
`getProductsByCategory` itself, but **`POST /api/product` now returns the
full, populated list** once two fields missing from every earlier guess
are added to the payload: **`categoryId`** and **`service`**.

**Resolved request shape** (live-confirmed, not a guess):

```json
{ "id": 9074, "cluster": "1_8", "categoryId": 666, "service": "DELIVERY", "Language": "En", "menuConfigId": "HRD_SA_23" }
```

**How this was found**: rather than guessing further, this session drove
a REAL "Customize" click in a real Playwright browser and inspected the
exact request it sent. Two UI obstacles had to be solved first (see
`investigation-log.md`): the "Customize" control is a styled `<span>`,
not a `<button>`, and every product card measures `0x0` until its
lazy-load image observer has fired at least once (fixed by scrolling
through the whole category page once before looking for it).

**Live-verified for all 6 required product families** (burger, meal/box,
side, drink/dessert, promotional item, plus a SIZE-variant switch) - see
`api-map.md` "Product detail endpoint" for the full table and
`research/shared/sample-responses/product-endpoint-resolved.json` for
the raw evidence. `POST /api/product-bundle-step` was ALSO resolved with
the same fix - it returns the same steps[] as a bare array, and its
`stepId`/`compId` parameters did not appear to filter the response in
any variant tried.

**One nuance discovered, not a composite-key issue as originally
theorized**: for a `bundle_group` wrapper product, the `id` to send is
the wrapper's own `selectedItem` field value (a different, nested numeric
id) - not a composite string key. Sending the wrapper's own top-level id
returns `HTTP 200` with an empty `data:{}`, which is exactly the failure
mode this item originally described.

**Practical impact**: `sauces`, `add_ons`, `sides`, `drinks`, and
`currency` in `field-map.json` are now all `observed`, not
`inferred_unresolved`/`not_observed`. A reusable tool for re-verifying
this endpoint against any product id was added:
[`../../tools/probe-product-endpoint.js`](../../tools/probe-product-endpoint.js).

> **Correction (2026-08-06, Streamlit-integration session):** the
> nested-item-id rule stated just above ("the wrapper's own `selectedItem`
> field value") was imprecise and has been corrected throughout this
> file, `api-map.md`, and `api-map.json`. `selectedItem` is that item's
> **`sku`**, not its **`id`** - live-confirmed while wiring
> `POST /api/product` into the Streamlit preview page: wrapper `77772960`'s
> `selectedItem=945` is a sku (matching `items[].sku=945`, whose own
> `id=12187`); sending `945` itself returns an empty `data:{}`, exactly
> like sending the wrapper's own top-level id `77772960` does. **Correct
> rule**: find the `items[]` entry whose `sku` equals `selectedItem`, and
> use that entry's own `id`. This was caught by a direct, non-Streamlit
> smoke test of the new `services/menu_service.py` module (see
> `resolve_detail_lookup_id()`) before the UI was ever loaded in a
> browser - every concrete id value quoted elsewhere in this project's
> docs (`12187`, `12189`, `10545`, ...) was and remains correct, since
> those came from real observed browser requests; only the one-sentence
> *derivation rule* was wrong.

## 2. Arabic locale behavior

Every call in this investigation used `Language: "En"` / `locale: "En"`
(the site's own default, matching what the real frontend actually sends
for an English-UI session). No `name_ar`/`description_ar` field was
populated on any category or product object, even though the field
*names* exist in the schema family KFC uses. Not tested:

- Whether a different `Language`/`locale` payload value (e.g. `"Ar"`)
  changes the response at all, 404s (as KFC's equivalent locale switch
  did), or requires an entirely different `menuConfigId`/`clusterId`.
- Whether the site's own Arabic UI (`/ar/home`, or the `عربي` toggle seen
  in the header) resolves to a different cluster with populated Arabic
  fields.

## 3. Progressive / tiered promotions

`getProgressivePromotion` (KFC's equivalent endpoint name) was **never
called** in this investigation - its existence for Hardee's specifically
was not even confirmed via the bundle grep (the compiled bundle's
endpoint table was grepped for literal `"/api/..."` strings, and
`getProgressivePromotion` did appear among the 90+ paths found - see
`../shared/frontend-analysis/bundle-findings.md` - but no live request was
attempted against it this session). `getPromotion` (the main, non-
progressive offers/promotions endpoint) WAS attempted live and is
confirmed to exist but not confirmed to return real data (see item 5
below). Neither endpoint's *populated* response shape is known.

## 4. Product deep links

No dedicated per-product URL/route was confirmed - category routes exist
(`/en/boxes/664`, etc.) but no `/en/.../<productId>` pattern was observed
or tested. `image_url` (a real, working asset URL) remains the only
confirmed per-product link, matching KFC's own fallback approach.

## 5. `getPromotion`, `product`, `product-bundle-step` request schemas

**UPDATE 2026-08-06 (second research session): `product` and
`product-bundle-step` are now RESOLVED - see item #1 above.** The fix
(adding `categoryId` and `service` to the payload) was found by observing
a real "Customize" click rather than further guessing.

**`getPromotion` remains unresolved - UPDATED 2026-08-07 (Streamlit-
integration session) with strong evidence it is likely dead/unreachable
code, not merely an untried payload.** This session:

1. **Tried the `categoryId`/`service` fix that resolved `/api/product`**
   (the leading theory from the previous update), plus every other
   plausible combination of real, observed identifiers: `cluster:"1_8"`,
   `menuConfigId`/`configId:"HRD_SA_23"`, `categoryId` (662 and 1480, both
   real promo-bearing categories), `service`/`orderType` (PICKUP and
   DELIVERY), `storeId` (24 and 5796), `cityId` (11), a real `promoId`
   (6544, "Double Treat Meal"'s own promo id) and `productId` (77772554),
   and an empty body. **Every single attempt returned the byte-identical
   `{"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR","message":"Invalid
   info provided"}`** - no combination produced a different error message
   or any field-specific hint, unlike `/api/product`, which returned a
   *different*, informative failure (`data:{}`) that pointed toward the
   real fix.
2. **Searched for a live UI trigger.** The homepage's "Great Offers"
   section (the only visible "offers" surface site-wide) is a bare static
   `<img>` inside a `<div>` with no `href`, `onClick`, or ARIA role at all
   - live-confirmed by dumping its DOM subtree. No "View all offers" /
   "See all deals" link exists anywhere on the homepage.
3. **Traced the client-side action creator itself in the compiled
   bundle.** The `getOffers`/`getPromotion` thunk is registered under the
   Redux action type `"offer/fetchAll"` and its implementation is a bare
   pass-through (`postData: {...e}` - whatever the caller supplies,
   verbatim, with no payload construction of its own). **Searching every
   downloaded bundle file (`spwa-ui`, `index`, `vendor`, `utils`) for any
   call site that actually dispatches this action found none** - the
   thunk is defined but never invoked anywhere in the current frontend
   build.

**Conclusion**: this is now best explained as **inactive/dead code**
inherited from the shared AMR platform (see api-map.md "Shared platform
note") rather than a live feature Hardee's simply hides behind a payload
this investigation hasn't guessed yet. Per the task's explicit
instruction, this does NOT count as "resolved" - no populated response
was ever obtained - but the *reason* it can't be resolved is now
evidenced rather than assumed. `getProgressivePromotion` (item #3) was
not re-tested this session and remains a separate open question.

## 6. Calories

Confirmed **not available as per-product structured data**
(`nutrition_facts` was an empty array on every one of 100+ products
sampled) - but ALSO confirmed this is intentional, not a missing/broken
field: `POST /api/getNutritionInfo` with an empty payload returns a
direct link to a static, whole-menu Nutritional Info PDF. This is a more
conclusive finding than KFC's equivalent ("empty array, cause unknown") -
see `api-map.md` "Known sentinel values and quirks". Not resolved: how
(or whether) that PDF's contents could ever be mapped back to per-product
calorie values programmatically (it is a PDF document, not structured
data) - almost certainly out of scope for an automated collector.

## 7. Delivery fees and minimum order value

Not observed anywhere in this investigation's scope, on either branch
tested. `validateLocation`'s successful response includes `promiseTime`
(prep+delivery estimate in minutes) and per-channel `advanceOrder`
eligibility, but no fee or minimum-order-value field. These almost
certainly only appear once a cart has at least one item (a
cart-total/fee-calculation call) - out of scope for this investigation
("Do not add many products to a cart"). `getPrepTime` is kitchen prep
time only, not a delivery-inclusive ETA - whether a separate
field/endpoint combines prep time with a drive-time estimate for a
specific delivery address was not identified.

**New, related open question (2026-08-06, second research session):**
`getPrepTime` returned the **identical** `{"prepTime":3}` for THREE
different stores tested across TWO different cities (Riyadh `storeId=24`;
Jeddah `storeId=97` and `storeId=7`), and `validateLocation`'s
`promiseTime` was `45` for both a Riyadh store (`5796`) and a Jeddah store
(`7`). This is a small sample (3 and 2 stores respectively), but the
exact-match pattern raises a real question: **is `prepTime`/`promiseTime`
a genuine per-store computation, or a platform-wide constant that happens
to look store-specific?** Not resolved either way - would need a larger,
more geographically/operationally diverse store sample (e.g. a
known-busy vs known-quiet branch) to tell apart.

## 8. Closed-store behavior

Not tested. KFC's investigation found a meaningful distinction between a
store's `active`/`sdmStatus` flags (real-time open/closed against daily
hours) and `cmsStatus` (whether the store still exists in the CMS at
all), with catalog data remaining available even for a currently-closed
store. Hardee's `getStoreList` response carries an analogous-looking
`active`/`sdmStatus`/`cmsStatus`/`active_status` set of fields (four
distinct flags, one more than KFC's three), but this investigation did
not happen to test against a store that was closed at request time, so
whether `getMenu`/`getProductsByCategory` behave the same way (continuing
to serve catalog data for a closed store) is unconfirmed.

## 9. Channel-specific price differences on a different cluster/branch - **substantially addressed 2026-08-06 (second research session), not fully closed**

This investigation's central finding - that Pickup and Delivery return
identical prices/offers - was originally confirmed for exactly **one**
cluster (`HRD_SA_23`/`1_8`, reachable from central-Riyadh test
coordinates).

**Re-tested this session against a second, ~950km-distant branch
(Jeddah)**, using two fully separate Playwright browser contexts (own
guest session, own deviceid, own cookie jar each):

- Pickup -> `storeId=97` ("TAHLIA-H", `cityId=31`, `areaId=8935`)
- Delivery -> `storeId=7` ("ANDALOS-WH", `cityId=31`, `areaId=8952`) - a
  DIFFERENT Jeddah store than the Pickup one, as expected for two
  independently-resolved channels

**Result: identical on every point compared.** Same `menuConfigId`
(`HRD_SA_23`), same `clusterId` (`1_8`), same 12 categories, and identical
`originalPrice`/`specialPrice`/`promoId` on every one of 40+ products
checked across 4 categories, for BOTH channels. The day-specific
`displayDay` promotion (`"Foodie Mix"`, SAT-only) reproduced identically
too. Full diff:
`../shared/sample-responses/channel-comparison-jeddah-vs-riyadh.json`
(machine-readable, `allSampledProductPricesIdentical: true`).

**What this now shows**: the original finding was NOT a one-branch
coincidence - it holds across two independently-tested, geographically
distant branches, strongly suggesting a single nationwide cluster.

**What remains open (why this item isn't fully closed)**:

- Only 2 of the country's ~35 cities were tested. A different city could
  still resolve to a different cluster - less likely now, but not
  disproven for every branch.
- The cart-level fee/minimum-order calculation was still never reached on
  either branch (no cart mutation was performed) - a channel difference
  could still exist there specifically, invisible to every endpoint
  actually tested in either research session.
- `/api/product`'s `service` field was confirmed to have no effect on
  price for ONE product (`id=9074`) on the ORIGINAL (Riyadh) branch only -
  it was not separately re-diffed with explicit `service=PICKUP` vs
  `service=DELIVERY` on the Jeddah branch specifically (though there is
  no structural reason to expect a different result, given the identical
  cluster).

## 10. `getStoreList`'s `storeIdAs` composite key

`"storeIdAs":"2_24_8072_2_HRD"` (pattern:
`<countryId>_<storeId>_<areaId>_<countryId-again>_<brand>`) appears on
every store object. No endpoint observed in this investigation consumes
this composite form specifically (every call used the bare numeric
`storeId`) - its purpose is inferred (perhaps a legacy/alternate lookup
key from an older API version) but not confirmed.

## 11. `validateLocation`'s automatic-banner coordinate source

The automatic `{screen:"HOME"|"CART", addressSubType:"DELIVERY"}` calls
that fire on every page load (before any Delivery UI interaction) used a
fixed coordinate (`24.795834165279, 46.629059761763`) that matched neither
the injected `navigator.geolocation` override NOR the Delivery modal's own
map-resolved pin, yet reproduced identically across multiple independent
browser sessions. Whether this is IP-based geolocation of this
investigation's own network egress point, a hardcoded fallback in
`getAppConfig`'s response, or something else was not identified - see
`investigation-log.md` step 6.

## 12. Request-volume / rate-pacing strategy - addressed 2026-08-07 (Streamlit-integration session)

Investigated for the batch product-detail preview tool
(`../../ui/batch_panel.py`) and the future production collector. Findings
from a live count against the Riyadh Pickup cluster
(`HRD_SA_23`/`1_8`, all 12 categories,
`research/shared/sample-responses/all-12-categories-pickup-default.json`):

- **110 unique product cards** across the 12 categories, with **zero
  ids appearing in more than one category** in this sample - no observed
  cross-category duplication (not proven impossible on every category
  combination, just not observed in the one full sweep checked).
- **53 of the 110 are `bundle_group` wrappers, and every single one of
  them has more than one SIZE/FLAVOR variant option** (almost always the
  3-way Regular/Medium/Large pattern). Fetching only the *default*
  variant's detail needs 1 call per card (110 calls total for full
  coverage at default-variant granularity). Fetching **every** variant's
  own price/modifier data (each is a structurally distinct nested item
  with its own id, price, and steps - see api-map.md "Product detail
  endpoint") needs one call per variant: 137 calls just for the 53
  wrappers' variants, plus 57 for the 57 simple/configurable products =
  **194 calls for one full, all-variant sweep of the entire catalog.**
  Bundle wrappers therefore **increase** total call volume versus a naive
  "one card = one call" assumption, if full variant coverage is wanted.
- **`/api/product-bundle-step` must never be called in addition to
  `/api/product` for the same product** - live-confirmed to return
  identical `steps[]` content (see api-map.md); calling both would
  simply double the volume for zero additional data.
- **Pickup and Delivery detail responses are confirmed byte-for-byte
  identical** for every product/field compared so far (base price,
  promoId, currency, and every individual modifier-option price - see
  `services/comparison_service.py` and the Streamlit comparison panel's
  live output, 43/43 fields identical on one wrapper product tested).
  **A future collector can therefore fetch `/api/product` ONCE per
  (product_id, categoryId, cluster, menuConfigId) and reuse the same
  response for both channels**, cutting a naive "fetch each channel
  separately" strategy's detail-call volume in half (194 -> 194 shared,
  not 388).
- **Recommended cache key**: `(lookup_id, category_id, cluster_id,
  menu_config_id)` - deliberately EXCLUDING `service`/channel and any
  `storeId`, since both are confirmed to have no effect on the response
  (see api-map.md "Channel separation mechanism"). `lookup_id` is the
  wrapper's resolved nested-item id (see
  `services/menu_service.py::resolve_detail_lookup_id`), not the
  wrapper's own top-level id.
- **No rate limiting was observed** across this investigation's full
  history (two research sessions plus this integration session -
  cumulatively several hundred sequential `/api/` calls at various
  paces, up to roughly one call per 500-800ms sustained): no `429`, no
  sudden `403`, no degraded latency pattern attributable to volume.
  This does NOT prove no limit exists at a higher volume/concurrency -
  only that the low, sequential pacing used throughout this project never
  triggered one.
- **Recommended production strategy** (documented in full in
  `api-map.md` "Request volume & rate-pacing strategy"): sequential
  requests only (no concurrency), a small fixed delay between calls
  (`ui/batch_panel.py` defaults to 0.6s, user-adjustable 0-3s), a bounded
  retry (2-3 attempts) with exponential backoff for network-level/5xx
  failures ONLY (a `DEFAULT_VALIDATION_ERROR`/422 business error should
  fail fast - retrying an already-wrong payload wastes a request and
  will never succeed), and the channel-reuse cache key above. Expected
  full-catalog request count for one daily run: roughly 15-20 bootstrap/
  category calls + 110-194 product-detail calls (depending on default-
  variant-only vs full-variant-coverage strategy) = **~125-215 total
  calls per day**, shared across both channels - not per channel.
