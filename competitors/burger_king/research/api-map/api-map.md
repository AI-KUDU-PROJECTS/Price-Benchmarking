# Burger King Saudi Arabia (`burgerking.com.sa`) API map

Burger King Saudi runs on **RBI's (Restaurant Brands International) global
digital-blue ordering platform** - the same platform family used by
Popeyes/Tim Hortons in other markets, fronted by two GraphQL backends:

1. `https://euc1-prod-bk-gateway.rbictg.com/graphql` and
   `https://euc1-prod-bk.rbictg.com/graphql` - the transactional API
   (restaurants, delivery availability, cart/checkout - though this
   project never calls the cart/checkout parts).
2. `https://czqk28jt.apicdn.sanity.io/v2023-08-01/graphql/prod_bk_sa/gen3`
   - a **Sanity.io CMS** GraphQL endpoint serving the menu content
     (categories, products, images, bilingual EN/AR names, PLU/modifier
     configuration).

**Both are fully public/unauthenticated** - every endpoint below was
replayed with a plain Node.js `https` request, zero cookies, zero
browser, and returned a normal `200` with real data. This means, unlike
KFC, **no Playwright bootstrap step is needed at all** for data
collection - Playwright is only used here for the documented
[pricing gap](#known-limitation-live-prices) workaround and for
screenshot capture (`NEW_PRODUCT`/`NEW_OFFER` only, same as KFC).

## How this was verified

Live, headless-browser recon against `https://burgerking.com.sa/en/`
(cookie consent -> "Choose your location" -> Pickup/Delivery mode ->
address or branch selection -> menu) while recording every network
request, then re-replaying each captured GraphQL request standalone via
plain `https.request()` with **no cookies and no browser** to confirm it
truly needs no session. `GetRestaurants`, and `GetMenuSections` were
explicitly re-verified this way and returned identical `200` data.
`GetRestaurant` and `DeliveryRestaurant` were verified live end-to-end
through the real UI flow (including an authentic "Delivery Unavailable"
response for an out-of-hours branch, and a "We couldn't find your
address" / "You are far from this restaurant" confirmation dialog for a
test address - both real, expected server responses, not errors).

Two real-world quirks found only by doing this live (not from reading
the compiled JS alone):

- **`isAvailable` on `GetRestaurants` is not the same as "can take an
  order."** Several branches had `isAvailable:false` while
  `mobileOrderingStatus:"live"` (their real-time open/closed state at
  query time, not a permanent flag) - **`mobileOrderingStatus` is the
  field that actually gates whether pickup/delivery collection should be
  attempted for a branch.**
- **A `GetRestaurants` NEARBY search and a specific branch's own
  `DeliveryRestaurant`/pickup confirmation can disagree at boundary
  distances/times** - e.g. a branch listed "Open Now" in the nearby list
  still returned `storeStatus:"CLOSED"` moments later for an exact
  delivery quote, because delivery hours and dine-in/pickup hours differ
  per branch. Branch verification in this collector checks the
  **channel-specific** hours field, never just a single generic
  "is this branch open" flag.

## Branch selection

**Dabab Street (storeId `11474`)** is used as the default configured
branch: confirmed via `GetRestaurants` to have
`mobileOrderingStatus:"live"`, `hasDelivery:true`, `hasTakeOut:true`, and
`isAvailable:true` at verification time (2026-08-11). Any other branch
with `mobileOrderingStatus:"live"` from the same `GetRestaurants` NEARBY
response would also work (e.g. `Burger King - Riyadh Park Mall` /
storeId `24452`, `Burger King - Dareen Center` / storeId `8260`).

## Endpoints

### `POST /graphql` (`euc1-prod-bk-gateway.rbictg.com`) - `GetRestaurants`

Finds candidate restaurants near a coordinate. No auth. Request:

```json
{
  "operationName": "GetRestaurants",
  "variables": {
    "input": {
      "filter": "NEARBY",
      "coordinates": { "userLat": 24.7136, "userLng": 46.6753, "searchRadius": 8000 },
      "first": 1000,
      "status": "OPEN",
      "parallelFlag": false
    }
  },
  "query": "... (full query captured during development, ~3.6KB) ..."
}
```

Required headers (no cookie, no Authorization): `content-type:
application/json`, `x-ui-language: en`, `x-ui-region: SA`, `x-ui-platform:
web`, `x-user-datetime: <ISO8601 with offset>`, `x-session-id: <random
UUID generated per run>`.

Response: `data.restaurants.{pageInfo, totalCount, nodes[]}`. Each node
carries `storeId`, `isAvailable`, `hasMobileOrdering`,
`mobileOrderingStatus` (`live` | `temporary_unavailable`), `hasDelivery`,
`hasTakeOut`, `hasDriveThru`, `hasDineIn`, per-weekday
`curbsideHours`/`deliveryHours`/`diningRoomHours`/`driveThruHours`,
`physicalAddress`, `franchiseGroupName`, `currentLocalTime`. Confirmed
live: 15 real Riyadh branches for a central-Riyadh search.

### `POST /graphql` (`euc1-prod-bk-gateway.rbictg.com`) - `GetRestaurant`

Single-branch lookup by `storeId` - used as the branch-existence/hours
check (equivalent of KFC's `getStoreList` branch check, but resolves
directly by ID instead of scanning a city list):

```json
{ "operationName": "GetRestaurant", "variables": { "storeId": "11474" } }
```

Response: `data.restaurant.{available, curbsideHours, deliveryHours,
diningRoomHours, driveThruHours, currentLocalTime}`.

### `POST /graphql` (`euc1-prod-bk-gateway.rbictg.com`) - `DeliveryRestaurant`

Burger King's equivalent of KFC's `validateLocation` - checks delivery
availability + gets a delivery quote for a dropoff address:

```json
{
  "operationName": "DeliveryRestaurant",
  "variables": {
    "dropoff": {
      "addressLine1": "...", "addressLine2": "", "city": "Riyadh", "route": "...",
      "state": "Riyadh Province", "streetNumber": "...", "zip": "13511", "country": "SAU",
      "latitude": 24.75, "longitude": 46.62, "phoneNumber": ""
    },
    "searchRadius": 7998,
    "platform": "web"
  }
}
```

`phoneNumber` is always left empty - this project never submits a real
phone number to any endpoint. Response:
`data.deliveryRestaurant.{storeStatus, quote, nextEarliestOpen,
deliverySurchargeFeeCents, quoteId, unavailabilityReason,
preOrderTimeSlots, restaurant{...}}`. Live-verified twice, standalone
(no browser, no cookies): once returning `storeStatus:"CLOSED"` /
`quote:"QUOTE_UNAVAILABLE"` for a real Riyadh address outside the
resolved branch's delivery hours (correct, expected behavior - logged as
an unavailable-location result rather than an error), and once (moments
later, a different nearest branch resolved) returning
`storeStatus:"OPEN"` / `quote:"QUOTE_SUCCESSFUL"` with a real `quoteId`.
**Uses the `-gateway` host**, confirmed by capturing the actual request
URL rather than assuming it groups with `AbTestFlags` on the plain
`euc1-prod-bk.rbictg.com` host (an assumption that was initially wrong
and caught by a standalone-replay smoke test during development - see
`collector/api-client.js`).

### `POST /v2023-08-01/graphql/prod_bk_sa/gen3?operationName=GetMenuSections` (`czqk28jt.apicdn.sanity.io`)

The full menu structure - **not store-scoped**, returns the same content
regardless of branch/channel:

```json
{ "operationName": "GetMenuSections", "variables": { "id": "9670fe1e-0342-41b7-9f92-a8fb1907120f" } }
```

`variables.id` is the `Menu` document's Sanity `_id` - re-read each run
from the `featureMenu` query's `defaultMenu._id` field rather than
hardcoded, in case Sanity content is republished under a new id.

Response shape: `data.Menu` -> `options[]` (sections/categories, each
with bilingual `name.locale`/`name._locFb`) -> each section's own
`options[]` (products, `_type` is `"combo"` for a deal/meal or `"item"`
for a single product) with `_id`, `name.locale`/`name._locFb`,
`image.asset.url`, and (for combos) a nested modifier/component tree
carrying **PLU codes** (`constantPlu`, `sizeBasedPlu`, `discountPlu`,
etc.) per POS vendor (`ncr`, `partner`, `sicom`, ...). These PLU codes are
what the real point-of-sale uses to look up a price - **they are not
prices themselves**.

#### Known limitation: live prices

**No price field of any kind exists anywhere in the `GetMenuSections`
response** - confirmed by exhaustively grepping the full ~250KB response
for `price`, `cost`, `amount`, `Cents`, and the literal SAR values
visibly rendered on the page (e.g. `39.00`) - none matched. Prices
clearly ARE fetched and rendered client-side once a store is selected
(confirmed live: real prices like `CHEESEBURGER LOVERS SAR 39.00`,
`WHOPPER® SAR 29.00` appear in the rendered page), and grepping the
site's own compiled JS bundles found the responsible client-side state
(`isPricesLoading`, a `.prices` object, `price.default` / `price.min`
fields read off it) - but the exact network request that populates that
state was not captured during this session's research window despite
multiple full page-load-through-store-selection recording passes on both
GraphQL backends.

**This is deliberately documented rather than guessed.** Given a
price-monitoring tool cannot skip prices, `collector/price-scraper.js`
extracts prices directly from the rendered `/en/menu` page's visible text
(`"<PRODUCT NAME>\nSAR <price>"` pattern, matched by normalized product
name back to the `GetMenuSections`-sourced product), as a pragmatic,
transparently-documented deviation from the pure-API approach used for
menu structure. **A future session with manual browser DevTools (Network
tab, "Preserve log", slowly scrolling through every menu category while
watching for the request that fires as prices populate) would very
likely be able to close this gap properly** - see
`competitors/burger_king/README.md` "Known limitations."

#### Deal category

`GetMenuSections` groups every product into one of 10 CMS categories for
the configured branch/verification date (2026-08-11):
`KING DAILY DEALS` (9), `WHAT'S NEW` (9), `CRISPY & TENDER CHICKEN` (12),
`FLAME-GRILLED BURGERS` (7), `KING SNACKS` (15), `KING SAVERS` (7),
`KING JR. MEALS` (3), `SWEET TREATS` (7), `KING SAUCES` (4), `DRINKS` (15).

`KING DAILY DEALS` (categoryId `c0e92480-0bc4-4821-9760-28d18dd8fc89` at
verification time) is confirmed to be Burger King's own dedicated
combo-bundle-deals section - every one of its 9 products is `_type:
"combo"` with a name like `SHARE DEAL` / `GRAND SHARE DEAL` /
`KING FEAST FOR TWO` / `BIG KING XL DEAL`. This is the one category
`backend/offer_parser.py` treats as this brand's offer signal (domain
feedback, confirmed live 2026-08-11) - see that module's docstring.

`KING SAVERS` was investigated as a candidate and **rejected**: its 7
products are all `_type: "item"` (single items, not combos) and are
Burger King's individually cheapest core menu items at verification time
(`HAMBURGER`=5 SAR, `CHEESEBURGER`=6 SAR, `CHICKEN BURGER`=6 SAR,
`CHICKEN BURGER WITH CHEESE`=7 SAR, `DOUBLE CHEESEBURGER`=11 SAR,
`KING CHICKEN TASTY`=13 SAR, `DOUBLE KING CHICKEN TASTY`=13 SAR) - a
permanent budget/value menu, not time-limited or bundled deals. Separately:
`https://burgerking.com.sa/en/offers` (the site's own literal "Offers" nav
link) redirects to `/en/rewards/offers`, a **loyalty-program** page
requiring login ("Log in or join now to track points and redeem delicious
deals") - unrelated to either menu category and out of scope for this
collector (no login is ever performed - see README "Security &
compliance").

### `POST /v2023-08-01/graphql/prod_bk_sa/gen3` (`czqk28jt.apicdn.sanity.io`) - `featureMenu`

Resolves the current live `Menu` document's Sanity `_id`
(`data.FeatureMenu.defaultMenu._id`), which `GetMenuSections` above needs
as its `id` variable. Called once per channel collection run rather than
hardcoding a menu id, in case Sanity content is republished under a new
one. The rest of this query's payload (upsell/checkout-donation item
content) is not used - only `defaultMenu._id` is read.

## Endpoints observed but not used

- `AbTestFlags` (`euc1-prod-bk.rbictg.com/graphql`) - feature-flag list
  for the frontend's own A/B tests; irrelevant to data collection.
- A Sanity **GROQ** data-query endpoint,
  `https://czqk28jt.apicdn.sanity.io/v2023-08-01/data/query/prod_bk_sa`
  (a `GET` request with the query embedded in the URL, not a POST body -
  a *different* Sanity API surface than the GraphQL one above), used by
  the frontend for a `systemwideOffer`/`configOffer` lookup. Not used by
  this collector - offers are read off `GetMenuSections`'s PLU/discount
  configuration instead (see `backend/offer_parser.py`), consistent with
  the "do not classify an offer from name alone" rule already
  established for KFC.

## Schema validation

`collector/api-client.js`'s `schemaCheck()` (same pattern as KFC's)
requires: `GetRestaurants` -> `data.restaurants.nodes` is an array;
`GetRestaurant` -> `data.restaurant` is an object;
`DeliveryRestaurant` -> `data.deliveryRestaurant.storeStatus` present;
`GetMenuSections` -> `data.Menu.options` is an array.

## What is never recorded here (or anywhere in git)

- No login/account credentials (browsing and availability checks never
  require login on this brand's storefront).
- No real phone number - `DeliveryRestaurant`'s `dropoff.phoneNumber` is
  always sent empty.
- No cookies, device IDs, or session tokens are saved to disk or git -
  `x-session-id` is a random UUID generated fresh in memory per run.
- No payment, cart, or checkout call is ever made.
