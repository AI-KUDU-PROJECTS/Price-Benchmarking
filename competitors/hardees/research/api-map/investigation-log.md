# Investigation log

Chronological record of this phase's work. All timestamps are the session
date, 2026-08-06. All coordinates used are either a real Hardee's branch's
own published location (from a live `getStoreList` response) or a
generic, well-known point in Riyadh - never a real personal address.

## 1. Repository inspection (before touching the live site)

- Inspected `competitors/kfc/` end to end: `research/api-map/api-map.json`
  + `api-map.md` (structure/quality reference), `collector/api-bootstrap.js`
  (Playwright session-bootstrap pattern), `collector/api-client.js`
  (typed endpoint wrappers), `collector/sanitize-har.js` (redaction
  patterns), and the root README's "Architecture"/"Gitignore" sections.
- Inspected the Hardee's scaffold as it existed before this phase:
  `competitors/hardees/README.md`, `collector/README.md`,
  `backend/__init__.py`, `dashboard/page.py` (placeholder `render()`),
  `config/__init__.py` - confirmed all were empty/placeholder, matching
  the task's Step 1 expectation.
- Confirmed the root `package.json` already lists `playwright@1.61.0` as
  a dependency and that `~/.cache/ms-playwright` already has a Chromium
  build installed - no new install needed.
- Reusable pattern identified: API-first collection (browser bootstrap
  only to establish a session, then direct/same-origin HTTPS calls for
  everything else), per-channel isolation, sanitize-before-retain for any
  HAR evidence, and a machine-readable + human-readable pair of API-map
  documents. Explicitly NOT reused: any literal endpoint path, payload
  field name, or response shape - every one of those was independently
  re-derived from Hardee's own live traffic (see below).

## 2. Folder scaffolding

Created `research/{pickup,delivery}/{raw,sanitized}/`,
`research/shared/{frontend-analysis,sample-requests,sample-responses}/`,
`research/api-map/`, and `tools/` under `competitors/hardees/`. Added
git-ignore rules for `research/{pickup,delivery}/raw/*` (kept `.gitkeep`
placeholders) to the repo root `.gitignore`, alongside the existing
per-competitor generated-data patterns.

## 3. First live contact - homepage bootstrap

Exploratory Playwright script (headless Chromium, not a deliverable,
discarded after use) loaded `https://saudi.hardees.me/en/home` and
recorded every `/api/` call, cookies, and `localStorage`/`sessionStorage`.

**Findings:**
- Page loads successfully; title "Hardee's Food Offers KSA...".
- `guestLogin` fires automatically -> sets `t`/`_t` HttpOnly JWT cookies
  and `localStorage.profileDraft.deviceid`.
- `getAppConfig`, `getMenuConfig` (x2, one per orderType), `getStoreList`,
  `getMenu`, `getHome` (x3) all fire automatically within ~4 seconds of
  page load, with no user interaction.
- Console showed several CSP violations for third-party scripts (Hotjar,
  mFilterIt, Snapchat pixel, a Web Worker from a blob: URL) - all
  ad/analytics noise, not relevant to this investigation, and not
  something this investigation attempted to work around.
- A cookie-consent banner ("Got It" button) and the header's order-mode
  tabs (`Self-Pickup`/`Drive-thru`/`Carhop`/`Dine-in`) plus a separate
  `SELECT LOCATION` pill were identified as the main interactive surface.

## 4. Pickup flow discovery

- Clicking `Self-Pickup` opened a "Select Self-Pickup Location" modal
  (City/Store dropdowns + `USE MY LOCATION` + `Proceed`).
- Clicking `USE MY LOCATION` fired `POST /api/getNewStore {lat,lng}` ->
  resolved `{cityId:11, areaId:8072, storeId:24}` for coordinate
  `24.70452479, 46.66425169`.
- Read the full `getStoreList` response to find every Riyadh branch that
  supports both Pickup (`services.tak=1`) and Delivery (`services.del=1`),
  is `active=1`/`cmsStatus=1` - 18 of 46 Riyadh stores qualified.
  `storeId=24` ("EUROMARCHE-H") was chosen as the fixed test branch
  because its own published coordinate is what "USE MY LOCATION" was
  already tested against, making the Pickup flow's branch resolution
  fully deterministic for this investigation.
- **Flaky UI interaction discovered**: clicking a category tile
  (`Thick Burger`, etc.) or a product card's title text repeatedly failed
  Playwright's actionability check ("element is not visible") even after
  `scrollIntoViewIfNeeded()` + a settle delay + `force:true`. Root cause
  suspected to be the grid's lazy-loaded thumbnail containers not
  reporting a stable size until their own `IntersectionObserver` fires.
  **Resolution**: switched to calling `POST /api/getProductsByCategory`
  via `page.evaluate(fetch(...))` from inside the already-authenticated
  tab - same session, same cookies, still fully browser-mediated, just
  not routed through a DOM click. This became the approach
  `tools/capture-network.js`'s `sample-categories` step uses.
- First attempt at this same-origin `fetch()` used only
  `content-type: application/json` and got `HTTP 500
  {"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR","message":"Invalid info provided"}`
  for every category id tried. Inspecting a real browser-issued request's
  full header set (via the HAR) revealed the missing required headers:
  `brand`, `country`, `language`, `version`, `devicemodel`,
  `is-dark-mode`, `deviceid`, `refreshtoken`. Adding them fixed every
  category (all returned `HTTP 200`).

## 5. Full category sweep

Sampled all 12 real categories under `menuConfigId=HRD_SA_23`/
`clusterId=1_8` (discovered via a live `getMenu` call) in one sequential
batch (~800ms pacing between calls): `662, 664, 666, 667, 668, 669, 670,
661, 1480, 1494, 1471, 1527`. Saved as
`research/shared/sample-responses/all-12-categories-pickup-default.json`.
Notably, this sweep succeeded **before any explicit Pickup/Delivery
channel selection was made** in that particular browser session - the
default cluster was already active from page load alone.

Findings from inspecting the results: nested `bundle_group` -> `items[]`
product structure (first seen on category 664 "Boxes"); the
`specialPrice=0`/`promoId=-1` sentinel pair, independently re-confirmed
live (see api-map.md "Known sentinel values"); the `"delevery"` spelling
on every product/category `services` object; a day-of-week-scoped
`displayDay` field on a "Deal of the Day" item; standalone drink products
using separate SKUs per size rather than a size variant.

## 6. Delivery flow discovery

- Found the `SELECT LOCATION` pill is a **separate** UI element from the
  Pickup tabs (`<a href="...?modal=addaddress">`), not a fifth order-mode
  tab.
- Clicking it opened "Select Delivery Location" with a live Google Maps
  widget. The map auto-centered on the browser's geolocation and reverse-
  geocoded it to a street address shown under "Select Location".
- First manual run (coordinate `24.7136, 46.6753`) resolved to
  "7250 - Alsahafa - Riyadh"; clicking `CONFIRM LOCATION` fired
  `validateLocation {lat:24.7136,lng:46.6753,screen:"LOCATION",
  addressSubType:"DELIVERY"}` and returned `HTTP 200` with a full store
  object: `storeId=5796, name_en="Sulimanya- H"`.
- Also discovered, from the SAME homepage load (before any Delivery UI
  interaction), that the app automatically fires two more
  `validateLocation` variants on its own: `{screen:"HOME",
  addressSubType:"DELIVERY",lat:24.795834165279,lng:46.629059761763}` and
  `{screen:"CART",...}` - using a DIFFERENT coordinate than either our
  injected `navigator.geolocation` override OR the map widget's own
  resolved pin. This exact same coordinate pair
  (`24.795834165279, 46.629059761763`) reappeared identically across
  multiple, independent browser sessions launched hours apart - strongly
  suggesting a fixed IP-based (or otherwise session-independent) default
  location used only for this specific automatic banner check, distinct
  from the Delivery modal's own geolocation-driven map. This was
  live-observed repeatedly but its exact source (IP geolocation service,
  hardcoded fallback, etc.) was not identified - see unresolved-items.md.
- Both of those automatic calls returned "not deliverable"
  (`OUTSIDE_DELIVERY_AREA_CONFIRM_LOC` / `OUTSIDE_DELIVERY_AREA`) **as an
  HTTP 500 transport status**, with the real outcome (`409`/`400`) only
  inside the JSON body - documented as a quirk in api-map.md.

## 7. Building `tools/capture-network.js` - two iterations

- **First version**: `recordHar` with `content:'embed'` and no request
  blocking. First live run took several minutes and had to be manually
  stopped - root cause: embedding every response body for every
  third-party ad/analytics/tracker request (dozens per load: DoubleClick,
  Google Analytics, Hotjar, Sentry, ClevertapProd, TikTok pixel, etc.)
  into the HAR, several of which are slow to resolve.
- **Fix**: added a `context.route()` allowlist that only lets through
  `*.hardees.me`, `*.americanarest.com`, `*.blob.core.windows.net`
  (Hardee's own domains + its CDN), plus `*.googleapis.com`/
  `*.gstatic.com` (needed for the Delivery flow's map widget - confirmed
  as a genuine first-party-configured CSP dependency, not ad/analytics
  noise - see the site's own CSP header quoted in
  `../shared/frontend-analysis/bundle-findings.md`). Also switched
  `recordHar` to `content:'omit'` (headers/timing/status only - the
  actual JSON bodies are captured separately, in full, in
  `api-calls.json`) once the first "omit"-free run produced a 15-25MB
  HAR file with no benefit (nothing needs an embedded map-tile image).
  Runs dropped from several minutes (or a manual kill) to ~15-20 seconds.
- **A second bug found via this fix**: a `page.waitForResponse(...)`
  promise created before a `.click()` that could itself fail (e.g. a
  disabled "Proceed"/"CONFIRM LOCATION" button) was never awaited if the
  click threw first, leaving it dangling; when the browser later closed,
  its eventual rejection surfaced as an **unhandled promise rejection
  that crashed the whole Node process**. Fixed by attaching `.catch(() =>
  null)` to every such promise immediately at creation time, before the
  subsequent click.
- **A UI-behavior bug found via the same fix**: with the googleapis/
  gstatic block in place, the "Select Delivery Location" map widget could
  not initialize at all (`use-places-autocomplete: Google Maps Places API
  library must be loaded` console errors), so `CONFIRM LOCATION` stayed
  permanently disabled. Fixed by allowing those two domains through the
  route allowlist (see above).

## 8. Final capture runs (the evidence this phase ships)

- `node tools/capture-network.js --channel=pickup` -> 26 `/api/` calls,
  `resolvedStore={"cityId":11,"areaId":8072,"storeId":24}` - identical to
  every earlier manual Pickup test.
- `node tools/capture-network.js --channel=delivery` -> 31 `/api/` calls,
  `resolvedStore.store={"storeId":5796,"name_en":"Sulimanya- H",...}` -
  **deliverable this time**, for the identical literal coordinate
  (`24.7136, 46.6753`) that an earlier manual run (step 6 above) had also
  found deliverable, but that a different automated run of the SAME
  script (before the googleapis/gstatic fix) found the map resolving to a
  non-deliverable "RRMB7104 - King Fahd Branch Road..." address instead -
  a genuine, reproducible-as-a-phenomenon (if not reproducible-as-a-value)
  inconsistency in the live site's own reverse-geocoding, documented in
  `../delivery/notes.md` rather than hidden.
- Both raw HARs + `api-calls.json` + `manifest.json` saved under
  `research/{pickup,delivery}/raw/<timestamp>/` (git-ignored). Sanitized
  with `tools/sanitize-har.js` (extended in this session to also handle
  the `api-calls.json` shape, not just real HAR files) into
  `research/{pickup,delivery}/sanitized/`. Verified programmatically
  (a small Node check script, not retained) that zero cookie/
  Authorization/deviceid header values or cookie-array values survive in
  either sanitized file.

## 9. Compiled frontend JS bundle analysis

Downloaded `spwa-ui-e89ec732.js`, `index-41f2264d.js`,
`vendor-5932c206.js`, `utils-85ad14db.js` (the site's own production
bundles) and grepped for the literal `{method:"...",path:"/api/..."}`
endpoint-definition table plus each interesting endpoint's request-thunk
implementation. Found and catalogued ~90 additional endpoint paths (most
out of scope - checkout/account/loyalty); the directly relevant subset is
in `../shared/frontend-analysis/bundle-findings.md`.

Live-probed 5 frontend-discovered endpoints with guessed payloads (2
attempts each, low-volume, sequential): `getPrepTime` and
`getNutritionInfo` both succeeded outright; `product`
(`getProductInfo`), `product-bundle-step`, and `getPromotion` all
returned real, structured error responses (HTTP 500
`DEFAULT_VALIDATION_ERROR`, or HTTP 200 with an empty `data:{}`) -
confirming each endpoint's existence without confirming a working
request schema. See `unresolved-items.md`.

## 10. Direct-API-access probe (no browser)

`tools/probe-public-api.js` (formalized from ad-hoc testing) made 3
sequential requests with Node's built-in `https` module, no cookie jar:

1. No headers at all -> `HTTP 403` from `Microsoft-Azure-Application-
   Gateway/v2` (WAF block, plain HTML body).
2. + browser-shaped headers, no `deviceid` -> `HTTP 500
   {"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR",
   "message":"Invalid info provided"}` (WAF passed it through; the
   application itself rejected it).
3. + a self-generated random 32-hex-char `deviceid`, still no cookie jar
   -> `HTTP 200`, `guestLogin` succeeded, `Set-Cookie` headers present.

Full transcript:
`../shared/sample-requests/direct-http-probe-transcript.md`.

## 11. Second research session (2026-08-06, later the same day): resolving `/api/product` and re-testing channel separation

Picked up from `unresolved-items.md`'s two recommended next steps.

**Resolving `/api/product`/`/api/product-bundle-step` (item #1):**

1. Re-read `api-map.md`/`unresolved-items.md` first (per task instructions)
   rather than re-deriving anything already established.
2. First attempt: dispatched a synthetic `MouseEvent('click', {bubbles:true})`
   directly on a product card's `[data-item-id]` container via
   `page.evaluate`, bypassing Playwright's actionability gate. **Failed
   silently** - no request fired. Investigation via
   `getBoundingClientRect()` revealed the element was genuinely `0x0` -
   there were 13-14 DUPLICATE DOM nodes sharing the same `data-item-id`
   (one per swiper/virtualization slide), and only ONE of them (whichever
   is currently in the mounted viewport) has real size at any moment.
3. Took a full-page screenshot to see what was ACTUALLY rendered, and
   found the answer had been visible the whole time: every product card
   has a **`Customize`** control next to its price, distinct from the
   **"+ Add to cart"** button below it - a styled `<span>`
   (`class="_customizeButton_..."`), not a `<button>` element, which is
   why an earlier button-only search never found it.
4. Fixed the sizing issue by scrolling through the ENTIRE category page
   once (`window.scrollTo` in a loop with a short pause) before looking
   for any element - this permanently fires every card's lazy-load
   `IntersectionObserver`, after which a normal
   `scrollIntoViewIfNeeded()` + `click()` works.
5. With both fixes in place, a real "Customize" click on product `id=9074`
   ("Super Star Mushroom Sandwich") fired `POST /api/product` with
   `{"id":9074,"cluster":"1_8","service":"DELIVERY","categoryId":666,
   "Language":"En","menuConfigId":"HRD_SA_23"}` and got back a FULLY
   populated response - 15 condiment options with real prices and
   Regular/Extra sub-tiers. The two missing fields versus every earlier
   guess: `categoryId` and `service`.
6. Repeated for: a `bundle_group` box (`id=77772960` "Roast Beef Box") -
   discovered the click actually requests the wrapper's `selectedItem`
   nested id (`12187`), not the wrapper's own id (sending `77772960`
   itself returns `HTTP 200` with empty `data:{}` - explaining the first
   session's exact failure symptom); a `configurable` side (`id=9118`
   "Crispy Curls", SIZE variant, which also fired `/api/productUpgrades`
   with near-identical data); a `configurable` dessert (`id=9121` "Mini
   Churros", FLAVOR variant); and a real, currently-discounted
   promotional item (`id=77772554` "Double Treat Meal", category 662,
   `originalPrice=65`/`specialPrice=49`/`promoId=6544` -> nested item
   `10545` with 14 build steps across two independent sandwiches).
7. Interacted INSIDE an already-open box-customize modal by clicking its
   "Large" size option - this re-issued `/api/product` with yet another
   nested item id (`12189`, price 44 vs Regular's 39), confirming size
   switches always resolve to a different concrete item id rather than
   modifying the same product's own state.
8. Retried `/api/product-bundle-step` with the SAME two-field fix
   (`categoryId` + `service`) applied to the original guessed payload -
   **succeeded** on the first attempt (`HTTP 200`, all 7 steps for
   product `12187`). Tried 4 payload variants (`stepId` only, `compId`
   only, both, `+groupId`) - all 4 returned the identical full 7-step
   array regardless of the `stepId`/`compId` value, suggesting the
   parameter does not actually filter anything server-side for this
   endpoint/product.
9. Directly tested whether `/api/product`'s accepted `service` field
   changes anything: called it 3 times back-to-back for the same product
   with `service:"DELIVERY"`, `service:"PICKUP"`, and the field omitted -
   all three returned byte-identical base price AND condiment-option
   prices. Also tested end-to-end: completed the full Self-Pickup
   branch-selection flow (Use My Location -> Proceed, confirmed
   `storeId=24`) FIRST, then customized the same product - the resulting
   `/api/product` call still sent `service:"DELIVERY"`, meaning the
   visually-selected Self-Pickup tab does not flip this field either.
10. Formalized the resolved request shape as a permanent, reusable tool:
    `tools/probe-product-endpoint.js` (new file, `node --check`-clean),
    then ran it live against both a `simple` product and a
    `bundle_group`-derived nested item id to confirm it reproduces
    everything found by hand above.

**Re-testing channel separation on a second branch (item #9):**

1. Selected Jeddah (cityId=31, 24 stores in `getStoreList`, ~950km from
   the original Riyadh branch) as a genuinely distant second branch,
   rather than another nearby Riyadh store.
2. Quick manual check first (before committing to a full capture): drove
   the Self-Pickup flow against a real Jeddah branch's own coordinate
   (`TAHLIA-H`, `21.55662781, 39.17014248`) and inspected the very first
   `getMenuConfig`/`getMenu` calls - found `storeId=97` resolved, and
   the SAME `menuConfigId`/`clusterId` (`HRD_SA_23`/`1_8`) and the SAME
   12-category list as Riyadh, before spending time on a full comparison.
3. Ran `tools/capture-network.js --channel=pickup --lat=21.55662781
   --lng=39.17014248` (its own fresh browser/session) -> `storeId=97`
   resolved again, reproducibly.
4. Ran `tools/capture-network.js --channel=delivery` in a SEPARATE
   process/browser/session (never sharing state with the pickup run)
   against the SAME coordinate first - **not deliverable** (consistent
   with the previously-documented reverse-geocoding non-determinism).
   Retried with a coordinate near a different Jeddah branch
   (`ANDALOS-WH`, `21.51462262, 39.16611246`) - succeeded, resolving
   `storeId=7`, a DIFFERENT store than the Pickup run's `storeId=97`, as
   expected for two independently-resolved channels.
5. Sanitized both new raw captures immediately
   (`tools/sanitize-har.js`, both the `.har` and `.json` shapes) into
   `research/{pickup,delivery}/sanitized/jeddah-branch/` - kept in a
   separate subfolder from the original Riyadh evidence so neither
   overwrites the other.
6. Programmatically diffed every product in 7 categories (all 12 were
   sampled; 4 were spot-checked line-by-line, all 7 sampled categories'
   full contents were diffed) between the Jeddah Pickup and Jeddah
   Delivery captures - **zero differences** in `originalPrice`,
   `specialPrice`, or `promoId` on any of 40+ products compared. Wrote
   the full diff to
   `research/shared/sample-responses/channel-comparison-jeddah-vs-riyadh.json`.
7. Cross-checked `getPrepTime` for `storeId=97`, `storeId=7`, AND
   `storeId=24` (Riyadh) in one single request batch (for a clean,
   directly-comparable result) - all three returned the identical
   `{"prepTime":3}`, which is documented as a new open question
   (possible constant) rather than treated as confirmation of anything.
8. Checked the Jeddah `validateLocation` success response for a delivery
   fee or minimum-order field - none present, matching Riyadh exactly
   (`promiseTime` only).

## 12. Third session (2026-08-07): Streamlit live-preview integration, getPromotion, request-volume strategy

Ordered per the task: (1) wire the resolved endpoints into a Streamlit
preview, (2) only once that's validated, continue researching
`getPromotion` and request-volume/rate-pacing strategy.

**Building the Streamlit preview:**

1. Inspected the root `app.py`/`pages/*.py`/`shared_ui/` structure and
   KFC's `dashboard/page.py`/`backend/config.py` for the pattern to
   follow (not copy - KFC's live-API layer is entirely Node.js; this
   phase needed a pure-Python client since Streamlit itself is Python and
   calls happen on-demand from widget interactions, not on a schedule).
2. Built `api/client.py` (a `requests`-based direct-HTTPS client -
   `requests` is already a hard transitive dependency of `streamlit`
   itself, confirmed via `pip show streamlit`, so no new root
   `requirements.txt` entry was needed), then `services/*.py`
   (branch/menu/comparison logic + a Python port of the HAR sanitizer's
   redaction rules), then `ui/*.py` (one Streamlit-rendering module per
   page section) and `dashboard/page.py` (orchestration).
3. **Before ever loading a browser**, ran a direct Python smoke test of
   the service layer (no Streamlit) against the live site - this caught
   a real bug immediately: `menu_service.get_product_detail()` returned
   `empty=True` for a real bundle_group wrapper (`id=77772960`, "Roast
   Beef Box"). Investigating why revealed a **documentation error from
   the second research session**: the wrapper's `selectedItem` field
   (`945`) is that item's **sku**, not its **id** - the real matching
   `items[]` entry (`sku=945`) has its own `id=12187`, which is the value
   `/api/product` actually needs. Every concrete id value quoted
   elsewhere in the docs (`12187`, `12189`, `10545`) was still correct
   (they came from real observed browser requests); only the one-sentence
   *rule* for deriving such an id from `selectedItem` was wrong. Fixed
   `resolve_detail_lookup_id()` to match `items[].sku == selectedItem`
   and use that entry's `id`; corrected `api-map.md`, `api-map.json`,
   `field-map.json`, and `unresolved-items.md` accordingly rather than
   leaving the error in place. Re-ran the smoke test - full 7-step
   modifier data returned correctly.
4. Launched the real Streamlit app (`streamlit run app.py --server.
   headless true`) and drove it with Playwright (navigate, click,
   screenshot, read rendered text) exactly like the live-site research
   itself - this is a real, screenshot-verified UI, not just a
   compiles-without-error check. This caught a SECOND real bug: the
   comparison panel raised `KeyError: ('DELIVERY', 5796, '1_8',
   'HRD_SA_23')` because only the "active" channel's `ChannelContext` was
   ever registered in the session-state lookup the `@st.cache_data`
   wrappers use (a dataclass instance can't be a cache key argument
   directly under Streamlit's own hashing rules). Fixed by extracting a
   shared `ui/state.py` module and having `branch_panel.py` register
   BOTH Pickup and Delivery contexts as soon as they're resolved,
   regardless of which one is "active" - not as a side effect of
   whichever panel happens to render first. A related product-lookup key
   was also simplified from `(channel_key, category_id, product_id)` to
   `(category_id, product_id)` alone, since `getProductsByCategory`
   itself carries no channel field - the same product dict is valid
   regardless of which channel's panel the user picked it from.
5. Re-validated end to end after both fixes: branch selection (dynamic
   City/Store dropdowns from a live `getStoreList`), category/product
   table, product-detail preview (burger AND a bundle_group wrapper,
   both showing full modifier data), category comparison (4/4 identical),
   and product-level comparison (43/43 fields identical, including every
   individual condiment price) all confirmed working via real screenshots
   - see `../../README.md` "Streamlit live API preview" for the
   walkthrough. Also caught and fixed a `st.tabs()` UX quirk (tab
   selection doesn't survive a rerun triggered by a button inside a
   different tab) by switching to a session-state-backed `st.radio()`.

**`getPromotion` research (task Phase 2):**

1. Looked for a live UI trigger first, per the task's instruction to
   prefer real frontend behavior over guessing. Dumped the homepage's
   "Great Offers" section DOM (the only visible "offers" surface
   site-wide) - it is a bare static `<img>` with no `href`, `onClick`, or
   ARIA role. No "View all offers" link exists anywhere on the homepage
   either (checked via a text-pattern search across every `<a>`/
   `[role=button]` element).
2. Re-fetched the compiled bundle fresh (byte-identical to the cached
   copy from the second session - no drift) and traced the `getOffers`
   thunk precisely: action type `"offer/fetchAll"`, implementation is a
   bare pass-through (`postData:{...e}`, no payload construction of its
   own). Searched every bundle file for any call site that dispatches
   this specific action (`np(` given its minified variable name) -
   **found none**, in `spwa-ui`, `index`, `vendor`, or `utils`.
3. With no real request to observe and no dispatch site to reverse from,
   tested 7 payload combinations via same-origin `fetch()` (matching the
   `/api/product`-resolution technique's fallback tier), using only real,
   already-observed identifiers (`cluster:"1_8"`, `menuConfigId:
   "HRD_SA_23"`, `categoryId` 662/1480, `service`/`orderType` PICKUP/
   DELIVERY, `storeId` 24/5796, `cityId` 11, `promoId` 6544, `productId`
   77772554) plus an empty body and an `{id:6544}` shape. **All 7
   returned the byte-identical `DEFAULT_VALIDATION_ERROR`** - no
   combination produced a different error or any field-specific hint.
4. Concluded (see `api-map.md` "getPromotion findings" and
   `unresolved-items.md` item #5): most likely dead/unreachable frontend
   code, not an unguessed payload. Left explicitly unresolved per the
   task's instruction (no populated response was ever obtained) - the
   evidence trail is what changed, not the resolution status.

**Request-volume / rate-pacing strategy (task Phase 3):**

1. Computed exact catalog-size numbers from the already-captured
   `all-12-categories-pickup-default.json` (no new live calls needed for
   this part): 110 unique product cards across 12 categories, zero
   observed cross-category duplicates, 53 `bundle_group` wrappers, every
   one with more than one SIZE/FLAVOR variant option, 137 total variant
   options. Saved the computation to
   `research/shared/sample-responses/catalog-size-analysis.json`.
2. Derived two coverage strategies (110 calls for default-variant-only,
   194 for full-variant coverage) and confirmed `/api/product-bundle-step`
   must never be called in addition to `/api/product` (identical
   content). Combined with the already-established
   Pickup/Delivery-identical finding to recommend a channel-shared cache
   key - see `api-map.md` "Request volume & rate-pacing strategy" for
   the full recommendation (sequential only, small fixed delay, bounded
   retry/backoff for transient failures only, fail-fast on validation
   errors).
3. Built `ui/batch_panel.py` (default batch size 5, hard cap 20,
   explicit Run button, adjustable delay slider, progress bar, success/
   failure counts) and validated it live via Playwright - 4/4 products
   fetched successfully in one real run, including two more bundle_group
   wrappers, confirming the `selectedItem`-sku fix generalizes beyond the
   one product it was originally found on.

## Failures encountered (kept here rather than silently fixed and forgotten)

- Clicking product-card title text directly: consistently failed
  ("element is not visible") - worked around via same-origin `fetch()`
  instead (see step 4).
- First `recordHar` approach: took several minutes / had to be killed -
  fixed via domain allowlisting + `content:'omit'` (see step 7).
- First same-origin `fetch()` attempt at `getProductsByCategory`: `HTTP
  500` due to missing app headers - fixed by copying the full header set
  from a real browser-issued request (see step 4).
- A dangling `page.waitForResponse()` promise crashed the whole capture
  process on an unrelated later event (browser close) - fixed with an
  immediate `.catch()` (see step 7).
- `product`, `product-bundle-step`, `getPromotion`: payload never
  resolved despite 2 guesses each informed by the bundle's own thunk code
  - left as explicitly unresolved (see `unresolved-items.md`) rather than
  guessed further or presented as confirmed. **Session 2 update:
  `product` and `product-bundle-step` were both resolved (see section 11
  above) - `getPromotion` alone remains in this state.**
- (Session 2) A synthetic `dispatchEvent(new MouseEvent('click'))` on a
  product card's container fired nothing and returned no error - the
  card was genuinely `0x0` (a virtualization/duplicate-DOM-node artifact),
  not a permissions or event-handling issue. Diagnosed by inspecting
  `getBoundingClientRect()` directly rather than assuming the click
  "worked" just because it didn't throw.
- (Session 2) The Jeddah Delivery test's first coordinate attempt (reusing
  the Pickup test's own coordinate) was not deliverable - not treated as
  a bug, just retried with a nearby coordinate, consistent with the
  already-documented reverse-geocoding non-determinism.
- (Session 3) A direct, non-Streamlit smoke test of `menu_service.py`
  caught the `selectedItem`-is-a-sku documentation bug (see section 12)
  BEFORE the Streamlit UI was ever loaded in a browser - this is exactly
  why that smoke test was run first rather than jumping straight to a
  browser-driven UI check.
- (Session 3) The Streamlit comparison panel raised a live `KeyError`
  the first time it was exercised end to end via Playwright (see section
  12) - only the "active" channel's context had been registered in the
  session-state lookup the cached functions rely on. Caught by actually
  clicking the button in a real browser, not by code review alone.
- (Session 3) `getPromotion`: 7 further payload combinations tried, all
  informed by real observed identifiers (never brute-forced ids) -
  still no populated response. Left explicitly unresolved, now with a
  much stronger evidenced explanation (dead/unreachable frontend code -
  see section 12) rather than left as a bare "still don't know".

## Changes made after live verification (vs. the first assumption going in)

- Assumed (by analogy with KFC) that `getMenuConfig`'s `orderType` would
  be the channel-fixing call. **Live testing disproved this** for the
  tested cluster - see api-map.md "Channel separation". This is the
  single biggest correction this investigation made to its own initial
  mental model, and it is documented as a finding, not silently dropped.
- Assumed `recordHar content:'embed'` was the right default (matching
  what a manual HAR export would do). **Live testing showed this was
  impractically slow** given the page's real third-party traffic volume -
  switched to `omit` + a domain allowlist.
- (Session 2) Assumed (per unresolved-items.md's own leading theory) that
  `/api/product`'s missing piece would be a *composite string key*
  (`productKey`/`aKey`) replacing the bare numeric `id`. **Live testing
  showed the real fix was two ADDITIONAL fields** (`categoryId`,
  `service`) alongside the same bare numeric id all along - the
  composite-key theory was not needed and was not correct.
- (Session 2) Assumed the "identical pricing across channels" finding
  might be specific to the one Riyadh cluster tested. **Live testing on a
  second, ~950km-distant branch (Jeddah) found the identical cluster and
  identical prices** - the finding generalizes further than originally
  known, though it is still not proven for every branch in the country
  (see unresolved-items.md item #9's remaining open sub-points).
- (Session 3) Assumed (and documented, incorrectly) that a bundle_group
  wrapper's `selectedItem` field could be sent directly to `/api/product`
  as the id. **A live smoke test showed `selectedItem` is that item's
  sku, not its id** - the real rule needs one more lookup step (match
  `items[].sku == selectedItem`, use that entry's `id`). Corrected
  throughout `api-map.md`, `api-map.json`, `field-map.json`, and
  `unresolved-items.md` rather than left as a silent code-only fix - see
  section 12.

## Session 4 (2026-08-11): production collector built

Following on directly from Session 3's live-preview work, this session
built the actual production Node.js collector + Python backend/dashboard
(`competitors/hardees/collector/`, `backend/`, `dashboard/`), copied
module-for-module from `competitors/kfc/` given the shared-platform
finding above, with brand-specific fixes only (`brand:"hrd"` in payloads,
etc.). A full live end-to-end `collect.js --channel=BOTH` run was the
first time this investigation exercised the complete pipeline (session
bootstrap through both channels' full category/product collection), and
it surfaced three real issues none of the first three sessions' more
targeted probing had hit:

- **`getStoreList`'s UTF-8 BOM.** Its response - served straight from
  Azure Blob Storage, not the app's own API layer - carries a leading
  U+FEFF byte. Every earlier session's manual/curl-style probes of this
  endpoint apparently either didn't hit this exact code path or tolerated
  it silently; a strict `JSON.parse()` in the real collector did not.
  Fixed by stripping the BOM in `http-client.js`.
- **Expired TLS certificate on `saudi.hardees.me` itself** - confirmed via
  a direct certificate check (`notAfter: Jul 20 2026`, checked
  2026-08-11), a real production issue on the target site's own
  infrastructure, unrelated to anything in this collector. Every module
  that connects to it now explicitly opts to tolerate this
  (`HRD_IGNORE_TLS_ERRORS`), documented loudly rather than silently
  patched over.
- **Transient `BlobNotFound` on `getStoreList`.** Confirmed via a direct
  diagnostic dump showing `STATUS:500` with an Azure
  `<Error><Code>BlobNotFound</Code>` XML body, clearing within 1-2 seconds
  on retry (3/3 immediate retries succeeded). Since `apiClient` calls
  never throw/reject by design (see `api-client.js`'s `call()`), this
  required a manual retry loop in `channel-collector.js`'s
  `verifyBranchExists()` rather than the existing exception-based
  `withRetry()` helper.

The production branch was independently re-derived this session
(`getStoreList`'s full 46-branch Riyadh dump, then live-verified via
`getNewStore`/`validateLocation`) and turned out to be **storeId 24,
EUROMARCHE-H** - the same `storeId=24` this document's earlier sessions
had already been using as their own worked example (see "Branch
selection" in api-map.md), confirming continuity rather than a
contradiction between the research-only and production-build phases.

Also live-verified (via Playwright, not assumed) three real UI-copy
corrections needed for `screenshot-capture.js`, none of which the
research-only sessions had reason to check since they never drove a real
browser through the full homepage flow: the cookie-notice button reads
"GOT IT" (not "ACCEPT & CONTINUE"), the hero button reads "Explore
Hardees Menu" (not "EXPLORE MENU"), and - most significantly - **the site
has no dedicated "Delivery" tab at all** in its top nav (only
Self-Pickup/Drive-thru/Carhop/Dine-in `role="tab"` elements exist);
Delivery is instead reached through the separate "SELECT LOCATION"
widget's "SELECT" badge, which opens a real "Select Delivery Location"
modal containing the genuine `CONFIRM LOCATION` button.
