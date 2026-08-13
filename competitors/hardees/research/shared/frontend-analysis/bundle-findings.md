# Compiled frontend JS bundle findings

Source: `https://saudi.hardees.me/assets/spwa-ui-e89ec732.js` (and
`index-41f2264d.js`, `vendor-5932c206.js`, `utils-85ad14db.js`) - the
site's own production JavaScript bundles, downloaded 2026-08-06 and
grepped for the literal endpoint-definition table
(`{method:"...",base:...,path:"/api/..."}`) that the app's Redux-Toolkit
`createAsyncThunk` action creators read from. This is the exact same
technique used for KFC's `getProductsByCategory`/`getProgressivePromotion`
in `competitors/kfc/research/api-map/api-map.md` "How this was verified"
step 3 - applied independently here, against Hardee's own bundle, not
copied from KFC's findings.

**Labeling convention used throughout `api-map.json`/`api-map.md`:**

- **Live verified** - a real request was made from a real browser (or a
  same-origin `fetch()` from within one) during this investigation and a
  real response was observed.
- **Frontend-code discovered, existence live-verified, payload/response
  not fully verified** - the endpoint's path+method came from this file,
  AND a live request against it returned a real (non-404) HTTP response
  from the application, but the exact payload needed to get useful data
  back was not resolved.
- **Frontend-code discovered, not live verified** - the endpoint's
  path+method came only from this file; no live request was attempted or
  none succeeded even at the "endpoint exists" level.

## Full endpoint table extracted from the bundle

Every `/api/...` path literal found in the bundle (`grep -oE
'"/api/[a-zA-Z0-9_/-]+"'`), grouped by relevance to this investigation.
Endpoints under `amr-loyalty/*` and `kfcloyalty/*` (Hardee's shares the
"Walaa"/AMR loyalty backend with KFC - see api-map.md "Shared platform")
and everything checkout/payment/account-related
(`sendOrder`/`sendCart`/`postAddress`/`paymentmethod`/`savedcards`/
`sendOtp`/`verifyOtp`/`createProfile`/`editprofile`/`deleteProfile`/...)
are **out of scope for this monitoring system** and were not called - they
are listed in api-map.json's `notUsedButObservedLive`/frontend-discovered
lists only for completeness, per the task's "search for" list.

### Directly relevant to menu/price/offer/branch mapping

| Path | Method (from bundle) | Relevance |
|---|---|---|
| `/api/guestLogin` | POST | session bootstrap - live verified |
| `/api/getAppConfig` | GET | config/SAS token - live verified |
| `/api/getStoreList` | POST | city/branch directory - live verified |
| `/api/getNewStore` | POST | nearest Pickup branch - live verified |
| `/api/validateLocation` | POST | Delivery location/branch resolution - live verified |
| `/api/getMenuConfig` | POST | menuConfigId/clusterId - live verified |
| `/api/getMenu` | POST | category list - live verified |
| `/api/getProductsByCategory` | POST | products/prices/offers per category - live verified |
| `/api/getHome` | POST | homepage banner rail (menuId passthrough) - live verified |
| `/api/getProgressivePromotion` | POST | tiered promos - frontend-discovered, not live verified in this run (path/payload shape mirrors KFC's own equivalent call, itself only inferred - see unresolved-items.md) |
| `/api/getPromotion` | POST | main promotions/offers list (`getOffers` thunk) - **frontend-code discovered, existence live-verified** (returned HTTP 500/`DEFAULT_VALIDATION_ERROR` for every payload guessed - see api-map.json) |
| `/api/getValidatePromotion` | POST | validates a specific promo/coupon - frontend-discovered, not live verified (would require an active coupon code to test meaningfully) |
| `/api/product` (`getProductInfo` thunk) | POST | single product detail - **frontend-code discovered, existence live-verified** (HTTP 200 but empty `data:{}` for every payload guessed - see api-map.json and unresolved-items.md "Hidden modifier groups") |
| `/api/product-bundle-step` (`getProductBundleStep` thunk) | POST | a bundle step's selectable options (sauces/add-ons/sides) - **frontend-code discovered, existence live-verified** (HTTP 500/`DEFAULT_VALIDATION_ERROR` for every payload guessed) |
| `/api/product/search` (`getSearchResults` thunk) | POST | product search - frontend-discovered, not live verified (out of scope: not needed for a fixed-branch daily collector) |
| `/api/getSearchTags` | POST | search autocomplete tags - frontend-discovered, not live verified |
| `/api/getNutritionInfo` | POST | **live verified** - empty payload `{}` returns `{"location": "<URL of a static PDF>"}`, i.e. a link to a whole-menu Nutritional Info PDF, not per-product structured calories. See api-map.md quirks. |
| `/api/getPrepTime` | POST | **live verified** - payload `{payload:{country,storeId}}` returns `{"prepTime": <minutes>}` (observed `3`). This is kitchen prep time, not a full delivery ETA - see unresolved-items.md. |
| `/api/getGreenConfig` | POST | "go green"/no-cutlery option config - frontend-discovered, not live verified, out of scope (not a price/menu field) |
| `/api/getupsell` / `/api/productUpgrades` / `/api/personaliseGetUpsell` | POST | cross-sell/upsell suggestions - frontend-discovered, not live verified, out of scope (not primary catalog data) |
| `/api/discountedItems` (`getDiscountedItem` thunk) | POST | frontend-discovered, not live verified - candidate for a cross-category "everything currently discounted" listing, worth checking in a future session |
| `/api/allstore` (`getStores` thunk) | GET | an alternate, GET-based store directory - frontend-discovered, not live verified; `getStoreList` (POST) was used instead since it was already confirmed live and richer |

### Payload shapes reconstructed from the bundle's own thunk code (candidate only, not live-confirmed to return populated data)

```js
// getProductInfo (POST /api/product) - reconstructed from the
// "fetch/getProductInfo" thunk. `d`/`o` come from Redux selectors for the
// current menuConfigId; live probe returned 200 with data:{} for this
// shape, so a required field is still missing (see unresolved-items.md).
{ id: <productId>, cluster: <clusterId>, menuConfigId: <menuConfigId> }
// the thunk also sets `excludeSteps: true` when the product's own
// bundleTypeId is 'configurable' or 'simple' AND the brand is 'phd'
// (Pizza Hut - a DIFFERENT Americana-platform brand also visible in this
// bundle's brand-switch logic - not Hardee's; hrd never sets excludeSteps).

// getProductBundleStep (POST /api/product-bundle-step) - reconstructed
// from the "fetch/getProductBundleStep" thunk; live probe with several
// guessed shapes (id+cluster+menuConfigId+configId, +compId, +stepId)
// all returned HTTP 500 DEFAULT_VALIDATION_ERROR - the real required
// field was not identified.
{ /* unresolved - see unresolved-items.md */ }

// getOffers (POST /api/getPromotion) - reconstructed from the "getOffers"
// thunk (top-level, distinct from the "personaliseServices.getPromotion"
// / "offer/fetchProgressive" thunks used for progressive/personalised
// promos). Live probe with orderType+cluster+configId+menuConfigId
// returned HTTP 500 DEFAULT_VALIDATION_ERROR.
{ /* unresolved - see unresolved-items.md */ }
```

## Notable code-level observations (support, not a substitute, for live verification)

- **`brand.toLowerCase()` branches** appear throughout the bundle
  (`"phd"`, `"hrd"`, ...) - Hardee's ("hrd") is one of several brand apps
  built from this SAME compiled bundle/platform (see api-map.md "Shared
  platform" - the `amr` config block and `appbundle:"com.kfc.me"` in
  localStorage both point the same direction). This is why endpoint
  *names* resemble KFC's so closely while payload/response *shapes*
  genuinely differ per brand in places (e.g. `excludeSteps` only applies
  to the `phd` brand, not `hrd`).
- **`getMenuConfig`'s selectors** (`Pr`, `jm`, `Lh` in the minified code)
  read the CURRENT Redux menu-config state rather than always issuing a
  fresh network call - consistent with the live observation that this
  session's `getMenuConfig` calls for `PICKUP` and `DELIVERY` both
  resolved to the identical `menuConfigId`/`clusterId` (see api-map.md
  "Channel separation").
- **CSP header** (read from a live response, not the bundle, but recorded
  here since it explains the third-party allow-list `tools/capture-network.js`
  needed): `script-src 'self' 'unsafe-inline' 'unsafe-eval'
  *.noonpayments.com *.facebook.net *.googletagmanager.com wzrkt.com
  *.azureedge.net *.googleapis.com *.cloudfront.net
  *.google-analytics.com *.googleadservices.com *.googleoptimize.com
  *.tiktok.com *.ads-twitter.com *.google.com *.gstatic.com
  *.clevertap-prod.com *.sentry.io tracking.kfc.me
  eu01.records.in.treasuredata.com cdp-eu01.in.treasuredata.com
  cdn.treasuredata.com`. `*.googleapis.com`/`*.gstatic.com` are why the
  Delivery flow's map widget needed those two domains allowed through
  `capture-network.js`'s request-blocking allowlist - they are a genuine
  first-party-configured dependency (Google Maps), not ad/analytics noise.
