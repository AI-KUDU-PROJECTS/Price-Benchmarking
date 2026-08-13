# Pickup investigation notes

See [`../api-map/api-map.md`](../api-map/api-map.md) for the full endpoint
reference. This file covers only what is specific to the Pickup channel
flow itself.

## Test setup

- Browser: Playwright Chromium (headless), fresh context per run.
- Geolocation override: `24.70452479, 46.66425169` - this is **the real,
  published coordinate of an actual Hardee's Riyadh branch**
  (`EUROMARCHE-H`, `storeId=24`, read directly from a live `getStoreList`
  response), not a fabricated or personal location. Chosen so
  "Use my Location" resolves deterministically to a stable, known branch
  every run.
- Locale: `en-US` / `Language: "En"` throughout - Arabic was not tested
  for Pickup (see `../api-map/unresolved-items.md`).

## Flow observed (live, repeated twice with consistent results)

1. Load `https://saudi.hardees.me/en/home`.
2. Dismiss the cookie-consent overlay (button text: `Got It`).
3. Click the **Self-Pickup** tab (already visually the default-selected
   order-mode tab, but clicking it is what actually opens the branch
   picker modal, "Select Self-Pickup Location").
4. Click **USE MY LOCATION**. This fires `POST /api/getNewStore` with the
   browser's `navigator.geolocation` position as `{lat, lng}` - live
   confirmed both times to resolve `{cityId:11, areaId:8072, storeId:24}`
   for our fixed coordinate.
5. Click **Proceed**. No further store-specific network call is required
   here for this cluster - see "Channel separation" in api-map.md: the
   `getMenuConfig` call already in flight (fired automatically on page
   load, before any user action) resolves the same `menuConfigId`/
   `clusterId` regardless of orderType, so nothing store-specific gates
   the catalog data actually collected.
6. Menu categories are reachable either by clicking a category tile
   (`Explore Menu` rail on the homepage, each backed by a real SPA route
   like `/en/boxes/664`) or, as this investigation ultimately did for
   reliable sampling, by calling `POST /api/getProductsByCategory`
   directly from within the already-authenticated page (see
   "Why direct in-page fetch instead of clicking product tiles" below).

## Branch / identifiers recorded

```
City:        Riyadh (cityId = 11)
Area:        areaId = 8072
Store:       storeId = 24, name_en = "EUROMARCHE-H"
Coordinates: 24.70452479, 46.66425169 (the store's own published location)
menuConfigId: HRD_SA_23
clusterId:    1_8
menuTempId:   8
```

`storeId=24` was resolved identically across every Pickup run in this
investigation (2 full `capture-network.js` runs + 3 earlier manual
exploration runs) - a stable, reproducible branch, matching the "one fixed
branch" requirement this future collector will need.

## Categories reached and sampled

All 12 real categories under `menuConfigId=HRD_SA_23`/`clusterId=1_8`,
confirmed live via `getMenu` and then individually via
`getProductsByCategory`:

```
662  App Exclusive             (4 products)   - offer/deal
664  Boxes                     (10 products)  - meal/box, configurable
666  Chargrilled & Thick Burgers (15 products) - burger
667  Hand Breaded Chicken      (18 products)  - chicken burger
668  Kids Meals                (3 products)
669  Sides Items               (14 products)  - side
670  Desserts & Beverages      (9 products)   - drink/dessert
661  Crave N' Save             (15 products)
1480 Deal of the Day           (7 products)   - offer/deal (day-of-week scoped, see api-map.md quirks)
1494 What's New - Overloaders  (7 products)
1471 What's New - One Piece    (4 products)
1527 What's New/ Tornado       (4 products)
```

Representative products opened/inspected from each required family:

- **Burger**: `id=9074` "Super Star Mushroom Sandwich" (simple, has a
  `Choose your condiments` step).
- **Meal/configurable**: `id=77772960`/item `12187` "Roast Beef Box -
  Regular" (bundle_group with SIZE variant + multiple build steps -
  "Choice of Box", etc.).
- **Side**: category 669 products (standalone fries/side SKUs).
- **Drink**: category 670 - standalone SKUs per size (e.g. `id=9000`
  "Pepsi Medium") rather than one product with a size variant; `id=9121`
  "Mini Churros" has a FLAVOR variant instead of SIZE.
- **Offer/deal**: `id=77773067` "Foodie Mix" (category 1480, `promoId=6744`,
  `limited_offer=1`, its nested item carries a `displayDay: {"SAT": [...]}`
  time-window - a Saturday-only deal).

## Why direct in-page `fetch()` instead of clicking product tiles

Product cards in the category grid render inside a virtualized/lazy
container (`data-item-id="<id>"` divs with a lazy-loaded thumbnail); in
several attempts, Playwright's actionability check reported the card
"not visible" even after `scrollIntoViewIfNeeded()` and a settle delay -
most likely the grid renders below-the-fold items with zero measured
height until their thumbnail's `IntersectionObserver` fires. Rather than
fight this further (which risks an unreliable, flaky collector later),
this investigation calls `POST /api/getProductsByCategory` directly via
`fetch()` executed **inside the already-loaded, already-authenticated
page** (`page.evaluate(...)`) - same-origin, same session, same cookies,
sequential with a pause between calls. This is still fully
browser-mediated (no external HTTP client), just not driven through a
DOM click, and it is exactly what `tools/capture-network.js`'s
`sample-categories` step does.

## Product-detail ("Customize") investigation - added 2026-08-06 (second research session)

The limitation above (no real product-detail modal opened) was resolved
this session. Two more UI quirks had to be worked around, on top of the
lazy-height issue already described:

1. **The "Customize" control is a styled `<span class="_customizeButton_...">`,
   not a `<button>` element** - a plain `page.getByRole('button', ...)`
   search never finds it.
2. **A full scroll-through of the category page, once, before looking for
   any specific card**, permanently fixes the lazy-height issue for every
   card on that page (their `IntersectionObserver`s all fire during the
   scroll) - after that, a normal `scrollIntoViewIfNeeded()` + `click()`
   on the "Customize" span works reliably.

With both fixed, a real "Customize" click was driven for one representative
product from every required family (burger, meal/box, side, drink/dessert,
promotional item) plus a variant-switch (SIZE: Regular -> Large) inside
an already-open modal. This resolved `unresolved-items.md` item #1 - see
`../api-map/api-map.md` "Product detail endpoint" for the full findings
and `../shared/sample-responses/product-endpoint-resolved.json` for the
raw evidence. No cart mutation occurred at any point (confirmed by
inspecting every `/api/` call made during each click - no
`sendCart`/`addToCart`/order endpoint ever fired, even for products whose
only visible control was "+Add to cart" rather than "Customize", since for
a `configurable`-type product that control opens a size-picker modal
first rather than mutating the cart directly).

## Second branch tested (Jeddah) - added 2026-08-06 (second research session)

To address `unresolved-items.md` item #9 ("was the 'identical pricing
across channels' finding a one-branch coincidence?"), a **separate**
`tools/capture-network.js --channel=pickup` run was made against a real
Jeddah branch's own published coordinate (`TAHLIA-H`,
`21.55662781, 39.17014248`) - its own fresh Playwright browser
launch/context/guest-session, sharing nothing with the original Riyadh
run.

**Resolved**: `{cityId:31, areaId:8935, storeId:97}` ("TAHLIA-H") -
reproducible, matching the coordinate's own published location.
**`menuConfigId`/`clusterId` resolved to the IDENTICAL `HRD_SA_23`/`1_8`
as the Riyadh branch** - see `../api-map/api-map.md` "Channel separation
mechanism" update for the full price/category comparison (all identical).
Raw evidence (git-ignored) and its sanitized copy live under
`raw/<timestamp>/` and `sanitized/jeddah-branch/` respectively, kept
separate from the original Riyadh evidence in `sanitized/` (not
`sanitized/jeddah-branch/`).

## What was NOT done (by design)

- Never added an item to the cart (see "Product-detail investigation"
  above for how this was confirmed even while testing "Add to cart"
  controls).
- Never logged in, never touched the "LOGIN" button visible in the header.
