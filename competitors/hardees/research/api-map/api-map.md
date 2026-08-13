# Hardee's Saudi (`saudi.hardees.me`) API map

**Phase: Implemented - see [`../../README.md`](../../README.md) for the
full production collector/backend/dashboard.** The sessions below cover
the original API-mapping investigation; the fourth session note
immediately following this paragraph covers the production build itself.
Machine-readable version: [`api-map.json`](api-map.json). Raw
field-level mapping to a future normalized schema:
[`field-map.json`](field-map.json). Full session-by-session trail:
[`investigation-log.md`](investigation-log.md). Everything not
conclusively verified: [`unresolved-items.md`](unresolved-items.md).

> **Fourth session (2026-08-11): production collector built.** Confirmed
> the shared-Americana-platform finding below extends all the way to a
> real, working, live-verified Node.js collector (`competitors/hardees/
> collector/`, copied module-for-module from KFC's with brand-specific
> fixes only) and a Python backend/dashboard - see
> [`../../README.md`](../../README.md) "Shared-platform discovery". Found
> and fixed three real, live-confirmed issues along the way, none of
> which were caught by the earlier research-phase sessions (which never
> exercised a full end-to-end collection run):
> 1. **UTF-8 BOM on `getStoreList`**: its response (served straight from
>    Azure Blob Storage, not the app's own API layer) carries a leading
>    U+FEFF byte that breaks `JSON.parse()` outright - fixed in
>    `http-client.js` by stripping it before parsing.
> 2. **Expired TLS certificate**: `saudi.hardees.me`'s own certificate was
>    found expired at verification time (`notAfter: Jul 20 2026`, checked
>    2026-08-11) - a real issue on the target site's own infrastructure.
>    Every module that connects to it now explicitly tolerates this via
>    `HRD_IGNORE_TLS_ERRORS` (default `true`), flagged loudly in code
>    rather than silently patched over.
> 3. **Transient `BlobNotFound` on `getStoreList`**: intermittently
>    returns HTTP 500 with an Azure `<Error><Code>BlobNotFound</Code>`
>    XML body that clears itself within 1-2 seconds on retry (3/3
>    immediate retries succeeded in testing) - fixed with a manual retry
>    loop in `channel-collector.js`'s `verifyBranchExists()`, since
>    `apiClient` calls never throw/reject by design.
>
> A full live end-to-end `collect.js --channel=BOTH` run succeeded:
> session bootstrap, `getStoreList` (46 real Riyadh branches),
> `getNewStore`/`validateLocation` both resolving **EUROMARCHE-H
> (storeId=24)** for the configured coordinates, `getMenuConfig`
> resolving `menuConfigId=HRD_SA_23`/`clusterId=1_8` (matching the
> earlier research session's own finding for the same coordinates - see
> "Branch selection" below), and **both channels returning 12/12
> categories, 110 real products each, status SUCCESS** - with real
> discount/promo products confirmed present (Sunday Duo 24→19 SAR/promoId
> 6739, Monday Double 62→39/6740, Friday Feast 137→75/6743, Super Night
> Deal 96→69/6742, Foodie Mix 30→25/6744, The Taster Mix 32→25/6741,
> Double Treat Meal 65→49/6544). Also see [`../../README.md`](../../README.md)
> "Screenshots" for the real UI-copy corrections found while verifying
> `screenshot-capture.js` against the live site ("GOT IT" cookie button,
> "Explore Hardees Menu" hero button, and the "SELECT LOCATION" → "Select
> Delivery Location" modal path used for Delivery, since **no dedicated
> "Delivery" tab exists in the top nav** - only Self-Pickup/Drive-thru/
> Carhop/Dine-in do).

> **Second research session (2026-08-06, later the same day):** resolved
> the product-detail endpoints (`/api/product`, `/api/product-bundle-step`
> - see [Product detail endpoint](#product-detail-endpoint) below and
> `unresolved-items.md` item #1) and re-tested the "Channel separation"
> finding against a second branch ~950km from the original one (Jeddah -
> see the update inside [Channel separation
> mechanism](#channel-separation-mechanism)). Everything added this
> session is marked with a `2026-08-06 (second session)` note inline so
> it stays distinguishable from the first session's findings.
>
> **Third session (2026-08-07): Streamlit live-preview integration.**
> Wired every resolved endpoint into a live Streamlit preview page (see
> [Streamlit live API preview](#streamlit-live-api-preview)) - a live
> smoke test caught and fixed a documentation error in the second
> session's nested-item-id rule (see the correction note inside [Product
> detail endpoint](#product-detail-endpoint)). Also investigated
> `getPromotion` further (see [getPromotion
> findings](#getpromotion-findings) - still unresolved, now with strong
> evidence it is dead code) and request-volume/rate-pacing strategy (see
> [Request volume & rate-pacing
> strategy](#request-volume--rate-pacing-strategy)).

All endpoints below are **public, first-party, unauthenticated (guest
session) endpoints** that the site's own browser frontend calls for every
anonymous visitor. Nothing here requires login, an OTP, a phone number, or
payment details. No cookie/token/deviceid *value* is ever written to this
file, to git, or to any log - see "Security & sensitive-data notes" below.

## Table of contents

- [Overall architecture](#overall-architecture)
- [Shared platform note](#shared-platform-note)
- [Browser bootstrap requirements](#browser-bootstrap-requirements)
- [Pickup flow](#pickup-flow)
- [Delivery flow](#delivery-flow)
- [Branch selection](#branch-selection)
- [Channel separation mechanism](#channel-separation-mechanism)
- [Menu / category / product sequence](#menu--category--product-sequence)
- [Product and offer response shapes](#product-and-offer-response-shapes)
- [Product detail endpoint](#product-detail-endpoint)
- [Required headers](#required-headers)
- [Session requirements](#session-requirements)
- [Direct API feasibility](#direct-api-feasibility)
- [Known sentinel values and quirks](#known-sentinel-values-and-quirks)
- [Known limitations](#known-limitations)
- [Security & sensitive-data notes](#security--sensitive-data-notes)
- [What a future collector should call, in order](#what-a-future-collector-should-call-in-order)
- [getPromotion findings](#getpromotion-findings)
- [Request volume & rate-pacing strategy](#request-volume--rate-pacing-strategy)
- [Streamlit live API preview](#streamlit-live-api-preview)

## Overall architecture

```
Browser loads /en/home
  -> guestLogin (auto)              guest session bootstrap, sets t/_t cookies
  -> getAppConfig (auto)            blob SAS token
  -> getMenuConfig (auto, x2)       fires for BOTH orderType=PICKUP and DELIVERY
                                     automatically - NOT gated by which tab
                                     is visually selected (see "Channel
                                     separation" below)
  -> getStoreList (auto)            full city/branch directory
  -> getMenu                        category list for the resolved cluster
  -> getProductsByCategory x N      per-category products/prices/offers
```

Every one of the calls above fires automatically within the first few
seconds of loading the homepage, before any user click - the site
pre-resolves a default branch/cluster (see "Branch selection" below) with
no user action required. Selecting Self-Pickup + a branch, or confirming
a Delivery address, mainly change *which specific store* is bound to a
subsequent `getMenuConfig` call (via `storeId` or the validated address) -
it did **not** change the catalog data returned for the one cluster this
investigation tested against (see "Channel separation").

## Shared platform note

Hardee's Saudi and KFC Saudi (`competitors/kfc/`) run on the **same
backend platform family**, operated by Americana Restaurants ("AMR"):

- `getAppConfig`'s response carries an `"amr":{"E":true,"S":"hrdbyamericana.com","ST":1}`
  block (KFC's equivalent config carries an analogous block for its own
  brand domain).
- Hardee's own guest-session `localStorage.profileDraft` carries
  `"appbundle":"com.kfc.me"` - a shared mobile-app bundle id across the
  group's brand apps, clearly a leftover/shared artifact rather than a
  Hardee's-specific value.
- The compiled JS bundle itself branches on `brand.toLowerCase()` values
  including `"hrd"` and `"phd"` (a different Americana brand, Pizza Hut) -
  see `../shared/frontend-analysis/bundle-findings.md`.

This explains why endpoint **names** (`getMenuConfig`, `getMenu`,
`getProductsByCategory`, `getNewStore`, `validateLocation`, `getStoreList`,
`guestLogin`, `getAppConfig`, `getHome`, `getProgressivePromotion`) are
identical to KFC's. It does **not** mean payloads or response shapes are
identical - every endpoint below was independently live-verified against
Hardee's own responses, and several are meaningfully different (see
"Known sentinel values and quirks").

## Browser bootstrap requirements

A fresh page load triggers, in order: `guestLogin` (sets `deviceid` in
`localStorage.profileDraft` and two HttpOnly guest-session JWT cookies,
`t`/`_t`) -> `getAppConfig` (blob SAS token) -> `getMenuConfig` (both
orderTypes) -> `getStoreList` -> `getMenu` -> `getProductsByCategory` per
category the UI happens to render. No CAPTCHA, no interstitial, no
account creation at any point for this guest flow.

The edge sits behind an **Azure Application Gateway WAF** that returns a
plain HTML `403 Forbidden` for any request missing browser-shaped
`user-agent`/`origin`/`referer` headers - live-confirmed directly with a
raw HTTP client (see "Direct API feasibility" below and
[`../shared/sample-requests/direct-http-probe-transcript.md`](../shared/sample-requests/direct-http-probe-transcript.md)).
This is the identical WAF behavior documented for `saudi.kfc.me`,
independently re-confirmed here on Hardee's own domain rather than
assumed.

## Pickup flow

See [`../pickup/notes.md`](../pickup/notes.md) for the full step-by-step
trail. Summary:

1. Click the **Self-Pickup** tab -> opens the "Select Self-Pickup
   Location" modal (City/Store dropdowns + "USE MY LOCATION" + "Proceed").
2. Click **USE MY LOCATION** -> `POST /api/getNewStore {lat,lng}` ->
   resolves `{cityId, areaId, storeId}` from the browser's geolocation.
3. Click **Proceed** -> closes the modal. No additional store-specific
   network call was observed to be *required* at this point for this
   branch/cluster (see "Channel separation").
4. Reach the menu (category tiles on the homepage, each a real SPA route
   like `/en/boxes/664`, or - as this investigation ultimately used for
   reliable sampling - a direct same-origin `fetch('/api/getProductsByCategory', ...)`
   from inside the already-loaded page; see pickup/notes.md for why).

**Fixed test branch used throughout this investigation:** Riyadh
(`cityId=11`), `storeId=24`, `name_en="EUROMARCHE-H"`, coordinates
`24.70452479, 46.66425169` (the branch's own published location, read
from a live `getStoreList` response - not a fabricated point). Resolved
identically across every Pickup run performed.

## Delivery flow

See [`../delivery/notes.md`](../delivery/notes.md) for the full
step-by-step trail, including an observed inconsistency worth reading
before relying on this flow. Summary:

1. Click the **SELECT LOCATION** pill (`<a href="...?modal=addaddress">`,
   a DIFFERENT UI element from the Pickup tabs) -> opens "Select Delivery
   Location" with a live Google Maps widget.
2. The map auto-centers on the browser's geolocation and reverse-geocodes
   it to a street-level address shown under "Select Location".
3. Click **CONFIRM LOCATION** (disabled/unclickable if the resolved
   address is not deliverable) -> `POST /api/validateLocation
   {lat,lng,screen:"LOCATION",addressSubType:"DELIVERY"}`.
4. On success, the response body already contains the **full resolved
   store object** (`data.store`) plus `data.menuId`/`data.menuTempId` - no
   separate branch lookup is needed.
5. This investigation stops here by design - the next real UI step is a
   full address-details form (street/building/floor/flat + a
   home/office/hotel/other tag + "Continue") that would create/save an
   address, explicitly out of scope.

**Test coordinate used:** `24.7136, 46.6753` (a generic, well-known
central-Riyadh point, not a real personal address). **One live run**
resolved to `storeId=5796`, `name_en="Sulimanya- H"` (deliverable); **a
second live run with the identical coordinate** resolved to a different,
non-deliverable address - see "Known limitations" below.

## Branch selection

Both channels ultimately need exactly one thing: a `storeId` (Pickup, via
`getNewStore` or a manually-picked City/Store dropdown pair) or a
validated `{lat,lng}` (Delivery, via `validateLocation`). Once resolved,
that `storeId` can be passed into `getMenuConfig` as an optional field,
but - see "Channel separation" immediately below - doing so did not
change this cluster's resolved `menuConfigId`/`clusterId` in any
combination tested.

**Production branch (confirmed 2026-08-11, fourth session):** `storeId
24` is **EUROMARCHE-H** - confirmed via a dedicated `getStoreList` dump
of all 46 real Riyadh branches, with the full object: `{cityId:11,
storeId:24, menuId:1, active:1, sdmStatus:1, cmsStatus:1,
name_en:"EUROMARCHE-H", name_ar:"هارديز اليورومارشيه",
services:{carHop:0,del:1,din:1,driveThru:1,tak:1},
location:{latitude:24.70452479, longitude:46.66425169, radius:500},
promiseTime:45}`. Both `getNewStore` (PICKUP) and `validateLocation`
(DELIVERY, `deliverable:true`) independently resolve back to this same
`storeId:24` for these exact coordinates - the same physical retail
location KFC's own EUROMARCHE/143 branch uses. This matches the
`storeId=24` used as an example throughout this document's earlier
research sessions below, confirming continuity between the original
API-mapping investigation and the production collector build.

## Channel separation mechanism

This is the single most important, and most surprising, finding of this
investigation. Answering the task's required questions directly:

1. **Which request starts a Pickup session?** Clicking the **Self-Pickup**
   tab opens the branch-picker modal; `getNewStore` (from "USE MY
   LOCATION") or a manual City/Store selection resolves the actual branch.
2. **Which request starts a Delivery session?** Clicking **SELECT
   LOCATION** opens the address modal; `validateLocation` (with
   `addressSubType:"DELIVERY"`) resolves the servicing branch.
3. **How is the selected branch linked to subsequent menu calls?** Via an
   *optional* `storeId` field on `getMenuConfig`'s request payload - but
   see #8 below, this had no observed effect on this cluster.
4. **Are Pickup and Delivery prices returned by the same endpoint?** Yes -
   `getProductsByCategory`, unconditionally, for both channels.
5. **Does the endpoint require different payload values?**
   **No, live-confirmed.** `getProductsByCategory`'s request payload
   (`{cluster, id, Language, configId}`) carries **no `service`/
   `orderType`/channel field of any kind** - a structural difference from
   KFC, whose equivalent call requires an explicit `service:
   "PICKUP"|"DELIVERY"` field.
6. **Are the products identical across both channels?** Yes, for every
   product spot-checked in this investigation (e.g. product `77772960`
   "Super Star Burger Combo": `originalPrice=38, specialPrice=0,
   promoId=6504` under both a Pickup-selected session (`storeId=24`) and a
   Delivery-selected session (`storeId=5796`)).
7. **Are offers different across both channels?** No difference observed
   in this investigation's testing - every product's `services` object
   (`carhop/delevery/dine_in/drivethru/take_away`, each `0|1`) already
   flags per-channel availability *within one shared response*, rather
   than the API returning two different catalogs.
8. **Can the same Product ID have different prices by channel?** Not
   observed in this investigation - every `getMenuConfig` call made
   during either channel's flow (`{"orderType":"PICKUP"}`,
   `{"orderType":"DELIVERY"}`, with and without `storeId`) resolved to the
   **identical** `menuConfigId:"HRD_SA_23"`/`clusterId:"1_8"`, and
   `getProductsByCategory` is keyed only on `cluster`/`configId`/category
   `id` - there is no channel-specific catalog to diverge from in the
   first place, for this cluster.
9. **Is branch selection required before menu retrieval?** No - `getMenu`
   and `getProductsByCategory` both succeeded automatically on page load,
   before any Pickup/Delivery selection was made, using whatever default
   cluster the session resolved on its own.
10. **Can menu APIs be called directly after browser bootstrap?** Yes -
    live-confirmed: a same-origin `fetch()` to `getProductsByCategory`
    succeeded immediately after `guestLogin`/`getAppConfig`/
    `getMenuConfig` completed, with no Pickup/Delivery UI interaction at
    all (see `tools/capture-network.js`'s `sample-categories` step, and
    the `all-12-categories-pickup-default.json` sample, which was captured
    with **no** branch-selection step performed first).

**Conclusion:** for the one branch/cluster this investigation could
safely test against, Hardee's does **not** separate Pickup and Delivery
catalogs, prices, or offers at the `getProductsByCategory`/`getMenuConfig`
level the way KFC does. The per-product `services` flags are the only
channel-awareness signal found in this data - see "Known limitations"
below for exactly what this does and does not prove, and
`unresolved-items.md` for "Channel-specific price differences" as an
explicit open question (a *different* branch/cluster, or a delivery-fee/
minimum-order calculation that only happens once a cart has items, could
still behave differently - neither was tested).

### Update 2026-08-06 (second research session): re-tested against a second, distant branch

The single biggest caveat on the conclusion above was "only confirmed for
ONE cluster" (see "Known limitations"). This session re-ran the full
comparison against **Jeddah** (~950km from the original Riyadh branch,
`cityId=31` vs `11`), using **two entirely separate `capture-network.js`
runs** - each one its own Playwright browser launch, own guest session,
own `deviceid`, own cookie jar, never sharing in-memory state:

- **Pickup**: geolocation set to a real Jeddah branch's own coordinate
  (`TAHLIA-H`) -> `getNewStore` resolved `{cityId:31, areaId:8935,
  storeId:97}`.
- **Delivery**: a separate coordinate (near `ANDALOS-WH`) in a fresh
  context -> `validateLocation` resolved `{storeId:7, name_en:"ANDALOS-WH",
  cityId:31, areaId:8952}` - a **different** Jeddah store than the Pickup
  one, exactly as expected for two independently-resolved channels.

**Every single comparison point requested came back identical to Riyadh
AND identical between the two Jeddah channels themselves:**

| Comparison point | Riyadh (session 1) | Jeddah Pickup (storeId=97) | Jeddah Delivery (storeId=7) |
|---|---|---|---|
| `menuConfigId` | `HRD_SA_23` | `HRD_SA_23` | `HRD_SA_23` |
| `clusterId` | `1_8` | `1_8` | `1_8` |
| Category count/ids | 12 (662,664,666,667,668,669,670,661,1480,1494,1471,1527) | identical 12 | identical 12 |
| Product ids per category | (baseline) | identical | identical |
| Base prices (`originalPrice`) | (baseline) | **identical on every one of 40+ products checked** | **identical** |
| Variant prices (`specialPrice`) | (baseline) | **identical** | **identical** |
| Offer availability (`promoId`) | (baseline) | **identical** | **identical** |
| Offer prices | (baseline) | **identical** | **identical** |
| Day-specific promotion (`displayDay`) | `{"SAT":[...]}` on "Foodie Mix" | **identical `{"SAT":[...]}`** | **identical** |
| `getPrepTime(storeId)` | `{"prepTime":3}` (storeId=24) | `{"prepTime":3}` (storeId=97) | `{"prepTime":3}` (storeId=7) |
| Delivery fee / minimum order | not exposed anywhere | not exposed | not exposed (only `promiseTime:45`, same as Riyadh's `5796`) |

Full machine-readable diff:
[`../shared/sample-responses/channel-comparison-jeddah-vs-riyadh.json`](../shared/sample-responses/channel-comparison-jeddah-vs-riyadh.json).

**This answers `unresolved-items.md` item #9's open question directly**:
the "identical pricing across channels" finding is **not** a one-branch
coincidence - it reproduces exactly on a second branch/cluster ~950km
away, strongly suggesting Hardee's Saudi runs **one single nationwide
cluster** (`HRD_SA_23`/`1_8`) rather than a per-city or per-region one.
The channel-separation mechanism (whatever question is answered by
"none observable at the catalog/pricing level, for either cluster
tested") is now the confirmed answer to question 10 in this section's
list, not a single-branch fluke - see the explicit list below, updated:

**Explicit answer to "through which mechanism does channel separation
happen?"**: **no observable mechanism** at the `getMenuConfig` /
`getProductsByCategory` / `/api/product` level, across two independently
tested branches/clusters. `/api/product` DOES accept a `service` field in
its request body (unlike `getProductsByCategory`, which accepts none at
all) - so the *request body* mechanism exists structurally - but it was
live-confirmed to have **zero effect on the response** (see "Product
detail endpoint" above). No header, query parameter, store-selection
step, or guest-session state was found to change price/offer data by
channel either. The two remaining, untested candidates are: (1) a
cart-level fee/minimum-order calculation (never reached - no cart
mutation was performed), and (2) a genuinely different cluster reachable
from a branch this investigation's safe test coordinates never happened
to resolve to (now less likely given a ~950km-distant branch resolved
the identical cluster, but still not disproven for every branch in the
country).

## Menu / category / product sequence

```
getMenuConfig(orderType) -> {menuConfigId, clusterId}
  -> getMenu({menuConfigId, cluster, menu:<menuTempId>, service}) -> categories[]
    -> getProductsByCategory({cluster, id:<categoryId>, configId:<menuConfigId>}) per category
       -> products[] (see field-map.json for the full per-field mapping)
```

12 real categories were live-confirmed for `HRD_SA_23`/`1_8`: `App
Exclusive`(662), `Boxes`(664), `Chargrilled & Thick Burgers`(666), `Hand
Breaded Chicken`(667), `Kids Meals`(668), `Sides Items`(669), `Desserts &
Beverages`(670), `Crave N' Save`(661), `Deal of the Day`(1480), `What's
New - Overloaders`(1494), `What's New - One Piece`(1471), `What's New/
Tornado`(1527).

## Product and offer response shapes

Hardee's products nest up to **three levels**, genuinely different from
KFC's flatter shape:

```
getProductsByCategory response
  data (the category object itself)
    .products[]                 <- top-level card shown in the grid
        .typeId / .bundleTypeId   'simple'|'bundle_group' / 'bundle'|'bundle_group'
        .variants[]               SIZE/FLAVOR selector (lives HERE, not on nested items)
        .steps[]                  build-customization groups (title/type/min/max only - see below)
        .items[]                  ONLY on a 'bundle_group' wrapper: the real purchasable
                                    product(s) inside it, each with ITS OWN id/sku/price/
                                    promoId/description/steps/displayDay/...
```

A "simple" single sandwich still carries `bundleTypeId:"bundle"` (because
it has a customization step) even though it has no `items[]` at all -
`bundle` here means "has steps", not "is a multi-item combo". Only
`bundleTypeId:"bundle_group"` reliably means a real combo/box/deal.

**Offers are not a separate object type** - an "offer" is just a
product/item whose `promoId != -1`. A day-of-week-scoped deal (`id
77773067` "Foodie Mix", category 1480) additionally carried a
`displayDay: {"SAT": [{"from":"04:00:00","to":"20:00:00"}]}` field on its
nested item - see field-map.json `offer.offer_type`.

See [`field-map.json`](field-map.json) for the complete raw-field ->
normalized-field mapping, including every field explicitly marked
`not_observed` or `inferred_unresolved` rather than guessed.

## Product detail endpoint

**Added 2026-08-06 (second research session) - resolves
`unresolved-items.md` item #1.** `getProductsByCategory`'s `steps[]`
entries carry only a shell (`{title, type, minimum, maximum, isTopping}`)
with no options list - the actual sauce/add-on/side/drink/size/flavor
choices come from `POST /api/product`, which was NOT successfully called
in the first research session (every guessed payload returned an empty
`data:{}`).

**The fix**: the real frontend's own request - captured by driving a
genuine "Customize" click in a real Playwright browser rather than
guessing further - is:

```json
{ "id": 9074, "cluster": "1_8", "categoryId": 666, "service": "DELIVERY", "Language": "En", "menuConfigId": "HRD_SA_23" }
```

Two fields were missing from every earlier guess: **`categoryId`** and
**`service`**. Neither was present in the bundle's own reconstructed
thunk code (see `../shared/frontend-analysis/bundle-findings.md`) - they
were only discoverable by observing a real request.

**Two UI quirks had to be worked around to trigger this click at all**
(documented in full in `investigation-log.md`, this session's entry):

1. The "Customize" control is a styled `<span class="_customizeButton_...">`,
   not a `<button>` element.
2. Every product card measures `0x0` via `getBoundingClientRect()` until
   its lazy-loaded thumbnail's `IntersectionObserver` has fired at least
   once - which only happens after the page has been scrolled past that
   card's position. A full scroll-through of the category page before
   any click fixes this permanently for the rest of that page load.

**Nested-item-id resolution for a `bundle_group` wrapper**: clicking
"Customize" on a combo/box/deal CARD (e.g. `id=77772960` "Roast Beef
Box") does **not** call `/api/product` with that card's own id - it calls
it with a specific entry from the wrapper's own `items[]` array instead
(`id=12187`, "Roast Beef Box - Regular"). Sending the wrapper's own
top-level id returns `HTTP 200` with an empty `data:{}` (not an error -
just empty), exactly the failure mode the first session hit. **Switching
a SIZE/FLAVOR variant inside the open modal re-issues this same call with
yet another, different nested item id** (live-confirmed: choosing
"Large" for the Roast Beef Box re-called `/api/product` with `id=12189`,
price 44 vs Regular's 39).

> **Correction (2026-08-06, Streamlit-integration session):** the exact
> rule for finding that nested id was mis-stated in the second research
> session and is corrected here. It is **not** "the wrapper's
> `selectedItem` field value" verbatim - `selectedItem` is the currently-
> selected item's **`sku`**, not its **`id`** (live-confirmed: wrapper
> `77772960`'s `selectedItem=945`, which is `items[].sku` for the entry
> whose own `id=12187` - sending `945` itself to `/api/product` returns
> an empty `data:{}`; sending `12187` returns the full response). **The
> correct rule**: find the entry in the wrapper's own `items[]` array
> whose `sku` equals `selectedItem`, and use *that entry's* `id`. This
> was caught by a live smoke test while wiring the resolved endpoints
> into the Streamlit preview page (`services/menu_service.py`'s
> `resolve_detail_lookup_id()`) - every `id=12187`/`id=12189` value
> quoted elsewhere in this document was itself always correct (they came
> from real observed requests), only the one-sentence *rule* for deriving
> such an id from `selectedItem` was wrong. See
> `unresolved-items.md` for the write-up.

**Live-verified for all six required product families**, each returning
a fully populated `steps[].options[]` (and, where relevant,
`variants[].options[]`) list - see
[`../shared/sample-responses/product-endpoint-resolved.json`](../shared/sample-responses/product-endpoint-resolved.json)
for the complete captured evidence:

| Family | Product | What was resolved |
|---|---|---|
| Burger (simple) | `id=9074` "Super Star Mushroom Sandwich" | 15-option "Choose your condiments" list, e.g. Swiss Cheese (default, price 2.5, Extra tier also 2.5), Pickles (not default, price 3, Extra 6), Tomato/Onion/Ketchup (free) |
| Meal/box (bundle_group -> nested item) | wrapper `77772960` -> item `12187` "Roast Beef Box - Regular" | 7 steps: Choice of Box (1), Choice of Sandwich (1), condiments (12), **Choice of side item (6, prices 0-7 SAR)**, **Choice of Beverages (6, prices 0-7 SAR)**, Choice of Tender (2), **Add Ons (11, prices 0-7 SAR)** |
| Side (configurable) | `id=9118` "Crispy Curls" | SIZE variant: Medium (selected) / Large; also fired `/api/productUpgrades` with near-identical data |
| Drink/dessert (configurable) | `id=9121` "Mini Churros" | FLAVOR variant: Sweet Creamy / Caramel (selected) - confirms `currency:"SAR"` field too |
| Promotional item (bundle_group -> nested item) | wrapper `77772554` "Double Treat Meal" (originalPrice 65, specialPrice 49, promoId 6544) -> item `10545` | 14 steps - TWO independent sandwich+condiments+side+beverage step-groups (a genuinely multi-sandwich deal) plus one shared Add Ons step. The nested item's own `originalPrice=49` already equals the wrapper's `specialPrice` - the discount is baked into the nested item, not double-applied. |
| `product-bundle-step` | same `id=12187` as the box above | Returns the SAME 7 steps as `/api/product`'s own `steps[]`, as a bare top-level array. The `stepId`/`compId` request fields did **not** filter the response in any of 4 variants tried - it appears to always return everything. Its purpose relative to the already-complete `/api/product` response was not conclusively determined. |

**The `service` field is accepted but has no effect on price**:
live-confirmed by calling `/api/product` for the same product
(`id=9074`) three times back-to-back with `service:"DELIVERY"`,
`service:"PICKUP"`, and the field omitted entirely - all three returned
byte-for-byte identical `originalPrice`/`specialPrice`/`promoId` AND
identical condiment-option prices. This was also true after *explicitly*
completing the full Self-Pickup branch-selection flow first (Use My
Location -> Proceed, confirmed `storeId=24` resolved) - the very next
`/api/product` call still defaulted to `service:"DELIVERY"`, meaning the
visually-checked "Self-Pickup" tab does not flip this internal field
either. See "Channel separation mechanism" below for how this reinforces
the original finding at the modifier-price level, not just the base-price
level.

**`defaultSelected` is not a reliable single-choice indicator.** Within
one `radio`-type step (e.g. "Choice of side item", "Add Ons"), MULTIPLE
options carried `defaultSelected:1` simultaneously in the live response -
not just the one actually pre-checked in the UI. Treat this field as
"eligible", not "the chosen default", if a future collector reads it.

## Required headers

Every `/api/` call observed live required these headers (values are
non-secret and static per session, except `deviceid`):

```
brand: HRD
country: KSA
language: En
version: v20
devicemodel: Chrome
is-dark-mode: 0
deviceid: <client-generated string - see "Direct API feasibility">
refreshtoken: "" (empty string is valid on a first call)
```

Plus, when calling from outside a real browser context (see below):
`user-agent`, `origin: https://saudi.hardees.me`,
`referer: https://saudi.hardees.me/en/home` - required to pass the WAF,
not the application itself.

## Session requirements

- **Cookies**: `guestLogin`'s response sets `t` (guest-auth JWT,
  HttpOnly/Secure/SameSite=Strict) and `_t` (refresh JWT, same flags).
  Neither was required as a *prerequisite* for any call tested in this
  investigation (every call worked from a cookie-less client once the
  `deviceid` header was present) - they appear to be how the *site's own
  frontend* persists identity across page loads, not a hard server-side
  gate on the endpoints themselves.
- **deviceid**: required on every call; a plain client-chosen string, no
  attestation observed (see below).
- **No bearer token / Authorization header** was required or observed on
  any call in this investigation.

## Direct API feasibility

**Yes, with two straightforward conditions**, live-confirmed with a raw
Node `https` client and zero cookie jar (see
[`../shared/sample-requests/direct-http-probe-transcript.md`](../shared/sample-requests/direct-http-probe-transcript.md)
and [`../../tools/probe-public-api.js`](../../tools/probe-public-api.js)):

1. Send browser-shaped `user-agent`/`origin`/`referer` headers, or the
   Azure Application Gateway WAF returns a plain HTML `403` before the
   request ever reaches the application.
2. Send a `deviceid` header with **any** value - a random 32-hex-char
   string generated with no registration step worked identically to a
   real browser's own generated value. Without it, the application layer
   itself returns `HTTP 500` with a structured
   `{"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR","message":"Invalid info provided"}`
   body (a real, informative error - not a WAF block).

Neither of these is an authentication bypass, a WAF bypass, or a
rate-limit evasion - they are exactly what a real browser's very first
request already sends by default. A future collector can therefore skip
Playwright bootstrap entirely for the request/response layer (Node's
built-in `https`, or any HTTP client capable of setting these headers, is
sufficient) - though see "Known limitations" for the one flow
(`validateLocation`'s reverse-geocoded address) that a Playwright-driven
real browser session was still needed to observe faithfully in this
investigation, since the map widget's own JS is what performs the
reverse-geocode.

## Known sentinel values and quirks

Every quirk below was **live-confirmed with a real request/response
pair**, not assumed from KFC's documentation:

- **`specialPrice: 0` does not mean free.** Confirmed on 8+ `bundle_group`
  wrapper products across 3 categories (e.g. `id=77772960`
  `originalPrice=39, specialPrice=0, promoId=17237`) - a real, positive
  `promoId` alongside `specialPrice=0` means "this endpoint just doesn't
  carry a simple fixed-discount price for this bundle shape", the same
  pattern documented for KFC, independently re-observed here.
- **`promoId: -1` means "no active offer".** Confirmed on 7+ simple
  sandwiches (`specialPrice == originalPrice` in every case).
- **`"delevery"` (not `"delivery"`) is the real, live key name** on every
  product/category `services` object - confirmed byte-for-byte in live
  responses, not a typo introduced by this documentation. The
  store-level `services` object (from `getStoreList`/`validateLocation`)
  correctly uses `del` as its short key instead - two different objects,
  two different spellings, do not conflate them.
- **Day-of-week/time-boxed offers exist.** `displayDay:
  {"SAT":[{"from":"04:00:00","to":"20:00:00"}]}` was observed on a live
  "Deal of the Day" item - a promoId being active right now does not mean
  it will still be active tomorrow, or even later today.
- **`validateLocation`'s "not deliverable" responses use HTTP 500 as the
  transport status**, with the real outcome (`409`/`400`) encoded only in
  the JSON body's own `statusCode`/`httpCode` fields - a client that
  checks only the HTTP status line will incorrectly treat every
  "not deliverable" result as a generic server error rather than a
  normal, expected business outcome.
- **Standalone drinks are separate SKUs per size**, not one product with a
  size variant (`id=9000` "Pepsi Medium" is a wholly separate product from
  a hypothetical "Pepsi Large") - size-as-variant only appears on combo/box
  wrapper products.
- **Nutrition is a whole-menu PDF, not per-product JSON** -
  `getNutritionInfo` returns `{"location": "<PDF URL>"}`; every product's
  own `nutrition_facts` array was empty on every sample, confirming this
  is by design, not a missing/broken field.
- **`getStoreList`'s store object is far richer than KFC's**, including
  `enterpriseUnit`, `deliveryMode`, `advanceOrder` (per-channel advance-
  order eligibility), `promiseTime` (minutes), and a composite
  `storeIdAs` key (`"2_<storeId>_<areaId>_2_HRD"`) whose consumer was not
  identified live - see unresolved-items.md.
- **`getPrepTime` and `validateLocation`'s `promiseTime` may not be
  genuinely store-specific.** (2026-08-06, second session) `getPrepTime`
  returned the identical `{"prepTime":3}` for THREE different stores in
  TWO different cities (Riyadh `storeId=24`, Jeddah `storeId=97` and
  `storeId=7`); `validateLocation`'s `promiseTime` was `45` for both
  Riyadh's `storeId=5796` and Jeddah's `storeId=7`. Neither is proven to
  be a hardcoded platform-wide constant (a larger, more diverse store
  sample would be needed to be certain), but the identical value across
  cities is suspicious enough to flag rather than trust at face value -
  see unresolved-items.md item #7.
- **A `bundle_group` wrapper's own top-level id is not what `/api/product`
  expects** - it expects the `id` of whichever entry in the wrapper's own
  `items[]` array has a `sku` matching the wrapper's `selectedItem` field
  (NOT `selectedItem` itself, which is a sku value, not an id - see the
  correction note under "Product detail endpoint" above), and switching a
  SIZE/FLAVOR variant resolves to yet another, different nested item id.
- **`defaultSelected:1` can appear on multiple options within the same
  single-select (`radio`-type) step simultaneously** - it does not
  reliably mark "the one pre-chosen option". See "Product detail
  endpoint" above.

## Known limitations

- **`getMenuConfig`'s channel-independence was originally confirmed for
  ONLY ONE cluster** (`HRD_SA_23`/`1_8`, reachable from central Riyadh
  test coordinates). **UPDATE 2026-08-06 (second session): re-tested
  against a Jeddah branch ~950km away (storeId=97 Pickup, storeId=7
  Delivery) and got the identical cluster, identical categories, and
  identical prices on 40+ products across both channels** - see "Channel
  separation mechanism" update above. This substantially weakens (but
  does not fully eliminate) the original concern - it remains
  theoretically possible that some OTHER branch in the country resolves
  to a different cluster, but two independently-tested, geographically
  distant branches now agree. A future collector should still re-verify
  this assumption if the configured branch ever changes to a third
  location.
- **`validateLocation`'s reverse-geocoded result was NOT perfectly
  reproducible** across two live runs using the identical literal
  coordinate - see `../delivery/notes.md` "A real, observed
  inconsistency". A future collector relying on one fixed
  Delivery coordinate should re-validate periodically rather than assume
  a one-time successful `validateLocation` call stays valid forever.
- **Sauce/add-on/side/drink option lists: RESOLVED 2026-08-06 (second
  session).** See "Product detail endpoint" above -
  `POST /api/product` (with `categoryId` and `service` added to the
  payload) returns them fully populated. This limitation from the first
  session no longer applies.
- **Delivery fee and minimum order value were not observed anywhere** in
  this investigation's scope, on EITHER branch tested (Riyadh or
  Jeddah) - both are order/cart calculations that likely only appear once
  a cart has items, which remains out of scope (no cart mutation was
  performed in either research session). See unresolved-items.md.
- **`getPrepTime`/`promiseTime` may be constants, not real per-store
  computations** - see the new quirk entry above. Not conclusively
  proven either way with only 3 stores sampled.
- **Arabic locale was not tested.** Every call in this investigation used
  `Language: "En"` / `locale: "En"` (the site's own default); no
  `name_ar`/`description_ar` field was populated on any category or
  product object even though the field names exist in the schema family
  KFC uses - whether a different locale parameter surfaces them was not
  tested.

## Security & sensitive-data notes

- Nothing in this file, `api-map.json`, `field-map.json`,
  `investigation-log.md`, or git history contains a real cookie value,
  JWT, deviceid value, or bearer token - see `tools/sanitize-har.js`'s
  redaction rules (cookies/Set-Cookie, Authorization/bearer/session/CSRF
  headers and body keys, JWT-shaped strings anywhere, precise
  coordinates, phone/email patterns).
- Raw HAR/`api-calls.json` captures live under `research/pickup/raw/` and
  `research/delivery/raw/`, which are **git-ignored** (see repo root
  `.gitignore`) - only the `-sanitized` copies under `research/*/sanitized/`
  are tracked. This includes the second session's Jeddah-branch captures
  (`research/{pickup,delivery}/sanitized/jeddah-branch/`), sanitized with
  the same `tools/sanitize-har.js` used throughout.
- `research/shared/sample-responses/product-endpoint-resolved.json` and
  `channel-comparison-jeddah-vs-riyadh.json` (added 2026-08-06) contain
  only public catalog/pricing data - no cookie, deviceid, or session
  value is present in either file (verified with a grep pass for
  JWT-shaped strings before being added to this repo).
- No login, OTP, real address, or payment detail was ever entered. No
  order was placed. No cart ever had an item added to it.
- The synthetic `deviceid` used in `tools/probe-public-api.js` is
  generated fresh in-memory each run and never written to disk.

## What a future collector should call, in order

For **each** channel independently (never mixing Pickup and Delivery
evidence into one undocumented run - see task requirements):

```
1. guestLogin                         -> establish session (deviceid, cookies)
2. getAppConfig                       -> blob SAS token (needed by #3, #5)
3. getStoreList                       -> verify the configured branch still exists/is active
4a. [PICKUP]  getNewStore(lat,lng)    -> confirm nearest branch is still the configured one
4b. [DELIVERY] validateLocation(lat,lng,screen="LOCATION",addressSubType="DELIVERY")
                                       -> confirm the configured coordinate is still deliverable
                                          and resolves to the configured branch
5. getMenuConfig(orderType, storeId?) -> menuConfigId, clusterId
6. getMenu(menuConfigId, cluster)     -> category list
7. getProductsByCategory(cluster, id, configId) per category
                                       -> products, prices, offers (see field-map.json)
8. [only for a product needing full modifier detail - see "Product
   detail endpoint"] product(id, cluster, categoryId, service,
   menuConfigId) -> populated steps[].options[] (sauces/add-ons/sides/
   drinks) and variants[].options[] (sizes/flavors). For a bundle_group
   wrapper, do NOT use its own top-level id or its `selectedItem` field
   directly - find the entry in its `items[]` array whose `sku` equals
   `selectedItem`, and use that entry's own `id` (see
   `services/menu_service.py::resolve_detail_lookup_id` for the reference
   implementation).
```

Given this investigation's "Channel separation" finding - now re-tested
on a second, distant branch with identical results (see the update above)
- steps 5-8 may turn out to return identical data for both channels on
whichever branch is currently configured. **A future collector should
still run both channels' full sequences and record whatever it actually
observes each day**, rather than assuming step 4's outcome (a different
price for the same product under one channel) can never happen. The one
thing this investigation is confident about is that nothing observed
*forces* such a difference to exist for either cluster tested - it does
not prove one can never appear on a third branch, or once a cart-level
fee calculation is involved (never tested - see unresolved-items.md).

## getPromotion findings

**Added 2026-08-07 (Streamlit-integration session). Status: unresolved -
no populated response ever obtained, but now with strong evidence
explaining why.** See `unresolved-items.md` item #5 for the full
day-by-day account; this section summarizes the conclusion.

`POST /api/getPromotion` (the `getOffers`/`"offer/fetchAll"` Redux thunk)
is confirmed to **exist** as a reachable endpoint (it returns a
structured `HTTP 500 {"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR"}`
body, not a 404), but every payload this project has ever tried - across
two research sessions, using every real, live-observed identifier
available (`cluster`, `menuConfigId`/`configId`, `categoryId`, `service`/
`orderType`, `storeId`, `cityId`, a real `promoId`, a real `productId`,
`Language`, and an empty body) - returned the **byte-identical** generic
validation error, with no field-specific hint of any kind.

Three independent lines of evidence now point to the same conclusion -
**this is very likely inactive/dead code in the current Hardee's
frontend build, not a live feature hidden behind an unguessed payload**:

1. **No live UI trigger exists.** The homepage's only "offers" surface
   (the "Great Offers" section) is a bare static `<img>` with no `href`,
   `onClick`, or ARIA role - confirmed by dumping its DOM subtree live.
   No "View all offers"/"See all deals" link exists anywhere on the site
   that this investigation could find.
2. **The action creator is never dispatched.** The compiled bundle
   defines the `getOffers` thunk (action type `"offer/fetchAll"`) as a
   bare pass-through with no payload-construction logic of its own - but
   grepping every downloaded bundle file (`spwa-ui`, `index`, `vendor`,
   `utils`) for any call site that actually invokes it found **zero**
   matches. Contrast this with `/api/product`'s thunk, which IS
   dispatched from a real, findable click handler - that's exactly how
   its correct payload was discovered.
3. **Every guessed payload fails identically**, unlike `/api/product`
   (which returned a *different*, more informative failure - an empty
   `data:{}` rather than a validation error - for its wrong-payload
   attempts, which was itself a clue toward the fix). `getPromotion`
   never varies its error at all, consistent with a validation layer that
   rejects every payload the same way regardless of which fields are
   present - the kind of behavior expected from an endpoint no real
   client traffic ever successfully exercises to keep working.

**What this means for a future collector**: offers/promotions data does
not need this endpoint. Every field a collector actually needs
(`promoId`, `specialPrice`, `disPercentage`, `limited_offer`,
`displayDay`) is already available per-product from
`getProductsByCategory`/`POST /api/product` - see field-map.json's
`offer.*` mappings, all of which are sourced from those two endpoints,
none from `getPromotion`. `getProgressivePromotion` (a different,
KFC-analogous endpoint - see unresolved-items.md item #3) was not
re-tested this session and remains a separate, still-open question -
it was never confirmed to be dead code the way `getPromotion` now is.

## Request volume & rate-pacing strategy

**Added 2026-08-07 (Streamlit-integration session)** - written for
`../../ui/batch_panel.py` and for whoever builds the production
collector next. Full research trail: `unresolved-items.md` item #12.

**Catalog size** (live count against Riyadh Pickup, `HRD_SA_23`/`1_8`,
all 12 categories): **110 unique product cards**, zero observed
duplicates across categories. **53 are `bundle_group` wrappers, and
every one has more than one SIZE/FLAVOR variant** (almost always the
3-way Regular/Medium/Large pattern) - each variant is a structurally
distinct nested item with its own id/price/modifiers (see "Product
detail endpoint" above).

**Two coverage strategies, two very different call counts:**

| Strategy | Detail calls needed |
|---|---|
| Default variant only (1 call per card) | 110 |
| Every variant of every wrapper (53 wrappers x their own variant count = 137, + 57 simple products x 1) | 194 |

**`/api/product-bundle-step` must never be called in addition to
`/api/product`** for the same product - confirmed to return identical
`steps[]` content (see "Product detail endpoint"); calling both doubles
volume for zero new data.

**Channel reuse cuts this in half again**: Pickup and Delivery detail
responses are confirmed byte-for-byte identical for every field compared
so far (base price, promoId, currency, every individual modifier-option
price - see "Channel separation mechanism" and the Streamlit comparison
panel's live 43/43-identical result on a real wrapper product). **A
collector should fetch `/api/product` ONCE per `(lookup_id, category_id,
cluster_id, menu_config_id)` and reuse the response for both channels**,
not fetch it once per channel. `lookup_id` is the resolved nested-item id
(see `services/menu_service.py::resolve_detail_lookup_id`), never the
wrapper's own top-level id, and never `service`/`storeId` (both confirmed
to have no effect on the response, so they do NOT belong in the cache
key).

**Rate limiting**: none observed across this project's full history (two
research sessions plus the Streamlit-integration session - several
hundred cumulative sequential `/api/` calls at various paces up to
roughly one call per 500-800ms sustained). No `429`, no sudden `403`, no
latency degradation attributable to volume. This does not prove no limit
exists at higher volume/concurrency - only that low, sequential pacing
never triggered one throughout this project.

**Recommended production strategy:**

- **Concurrency**: sequential only, no parallel requests - matches
  KFC's own collector pattern (`DELAY_BETWEEN_REQUESTS`, config-driven).
- **Delay**: a small fixed delay between calls (`ui/batch_panel.py`
  defaults to 0.6s, user-adjustable 0-3s in the Streamlit preview) - a
  considerate default, not a measured requirement (no limit was ever hit
  even at faster paces during research).
- **Retries/backoff**: bounded (2-3 attempts), exponential backoff, for
  network-level failures and unexpected 5xx ONLY. A `DEFAULT_VALIDATION_
  ERROR`/422 business error should fail fast without retrying - the
  payload is wrong, not transient, and retrying wastes a request.
- **Cache key**: `(lookup_id, category_id, cluster_id, menu_config_id)` -
  see above.
- **Channel reuse policy**: fetch once, apply to both PICKUP and
  DELIVERY - re-verify this assumption (a single spot-check per run is
  cheap) rather than hardcoding it forever, per "Known limitations".
- **Expected full-run request count**: ~15-20 bootstrap/category calls
  (guestLogin, getAppConfig, getStoreList, 2x getMenuConfig, getMenu,
  12x getProductsByCategory) + 110-194 product-detail calls (depending on
  variant-coverage strategy) = **roughly 125-215 total calls per day**,
  covering BOTH channels - not per channel.

## Streamlit live API preview (superseded 2026-08-11)

**Added 2026-08-07, superseded by the fourth session's production build**
(see the note at the top of this document). `../../dashboard/page.py` was
rebuilt in the fourth session to read from the real collector database
(`backend/database.py`) like every other competitor, and no longer
imports any of the modules described in this section. The description
below is kept for historical reference only - the code itself
(`api/client.py`, `services/*.py`, `ui/*.py`, `config/`) is still present
on disk but unused; see `../../README.md` "Superseded research-phase
code".

`../../dashboard/page.py` (reached via the existing `pages/2_Hardees.py`,
no router change needed) was a live-preview UI over every resolved
endpoint above, built as: `api/client.py` (a pure-Python direct-HTTPS
client - no Playwright/browser needed, per "Direct API feasibility"
above) -> `services/*.py` (the normalization/comparison rules from this
document and field-map.json, in one place each) -> `ui/*.py` (Streamlit
rendering, one module per page section, each `@st.cache_data`-wrapped so
a normal Streamlit rerun never silently re-hits the network). It was a
preview/inspection tool only - no database, no schedule, no
bulk/background collection.
