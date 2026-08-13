# Delivery investigation notes

See [`../api-map/api-map.md`](../api-map/api-map.md) for the full endpoint
reference. This file covers only what is specific to the Delivery channel
flow itself.

## Test setup

- Browser: Playwright Chromium (headless), **fresh context** - a clean
  browser context was used for the Delivery investigation, never sharing
  in-memory session state with a Pickup run (per the task's "start a
  clean browser context" instruction), though both ultimately talk to the
  same public guest-session bootstrap.
- Test coordinate: `24.7136, 46.6753` - a generic, well-known central
  Riyadh point (not a real personal address, not a specific building).
- Locale: `en-US` / `Language: "En"` throughout.

## Flow observed (live)

1. Load `https://saudi.hardees.me/en/home`, dismiss the cookie banner.
2. Click the **SELECT LOCATION** pill next to the order-mode tabs (an
   `<a>` with route `?modal=addaddress`, distinct from the Pickup tabs -
   see api-map.md "Channel separation mechanism", question 1/2).
3. The **"Select Delivery Location"** modal opens with a live Google Map
   (an actual first-party dependency of the site, allowed through
   `tools/capture-network.js`'s request-blocking allowlist - see
   `../shared/frontend-analysis/bundle-findings.md`) that auto-centers on
   the injected geolocation coordinate and reverse-geocodes it to a
   street-level address string shown under "Select Location".
4. Click **CONFIRM LOCATION**. This fires
   `POST /api/validateLocation` with body
   `{"lat":24.7136,"lng":46.6753,"screen":"LOCATION","addressSubType":"DELIVERY"}`.
5. **The button is disabled entirely (unclickable) when the reverse-
   geocoded address is not deliverable** - the modal shows "Sorry, we
   don't deliver here yet" inline and never lets the request fire at all.
   This happened in one live run where the coordinate happened to
   reverse-geocode to a King Fahd Road address just outside a delivery
   zone. On a second live run, the SAME literal coordinate reverse-
   geocoded to a different nearby address ("Sulimanya" district) that
   WAS deliverable, and the click succeeded - see
   "A real, observed inconsistency" below.
6. On success (HTTP 200), the response body already contains the FULL
   resolved store object - no separate store-lookup call is needed
   afterward:

   ```json
   {
     "statusCode": 200,
     "data": {
       "menuId": 1,
       "menuTempId": 8,
       "store": {
         "storeId": 5796, "countryId": 2, "areaId": 8104, "cityId": 11,
         "name_en": "Sulimanya- H", "name_ar": "السليمانيه",
         "isOnline": true,
         "services": {"carHop":0,"del":1,"din":1,"driveThru":1,"tak":1},
         "advanceOrder": {"carHop":0,"del":0,"din":0,"driveThru":0,"tak":1},
         "promiseTime": 45,
         "location": {"latitude":24.711699,"longitude":46.696966,"radius":500}
       }
     }
   }
   ```
7. **This investigation deliberately stopped here.** The very next UI
   step in the real product is a full address-details form (Street/
   Building/Floor/Flat/"How to Reach" + a home/office/hotel/other tag +
   a "Continue" button) that would create/save an address - explicitly
   out of scope ("Do not save a real address", "Do not add many products
   to a cart"). Everything needed for the API map (the resolved store,
   `menuId`, `menuTempId`, deliverability) was already in step 6's
   response body.

## A real, observed inconsistency (worth flagging, not hiding)

The exact same literal coordinate (`24.7136, 46.6753`) produced a
**different** reverse-geocoded street address - and therefore a
different deliverability verdict - across two separate live runs on the
same day. This is not a bug in this investigation's tooling; it is
genuine behavior of the live site's map/geocoding integration (Google's
reverse-geocoder can return more than one plausible nearby named place for
one coordinate, and this cluster's delivery-zone polygon boundary is
apparently narrow enough for that to matter). A future collector that
depends on Delivery deliverability at one fixed coordinate should
therefore not assume a single validateLocation call is perfectly
deterministic run-to-run - see `../api-map/unresolved-items.md`.

## Branch / identifiers recorded (successful run)

```
City:         Riyadh (cityId = 11)
Area:         areaId = 8104
Store:        storeId = 5796, name_en = "Sulimanya- H"
Coordinates:  24.711699, 46.696966 (the store's own published location, radius 500m)
menuId:       1
menuTempId:   8
menuConfigId: HRD_SA_23  (same value observed under Pickup - see "Channel
              separation" in api-map.md)
clusterId:    1_8         (same value observed under Pickup)
```

## Categories reached and sampled

Identical sampling to the Pickup run - the same 12 categories, via the
same `getMenuConfig`-resolved `menuConfigId=HRD_SA_23`/`clusterId=1_8` -
see `../pickup/notes.md` for the full list. Spot-checked product `id=77772960`
("Super Star Burger Combo") returned `originalPrice=38, specialPrice=0,
promoId=6504` under BOTH channels in this investigation, with no
observed price difference - see api-map.md "Are Pickup and Delivery
prices returned by the same endpoint?".

## Second branch tested (Jeddah) - added 2026-08-06 (second research session)

To address `unresolved-items.md` item #9, a **separate**
`tools/capture-network.js --channel=delivery` run was made against a
coordinate near a real Jeddah branch (`ANDALOS-WH` area,
`21.51462262, 39.16611246`) - its own fresh Playwright browser
launch/context/guest-session, sharing nothing with either the original
Riyadh delivery run or the Jeddah PICKUP run (`../pickup/notes.md`) - a
fully independent channel test on a fully independent branch.

**Resolved**: `validateLocation` returned `HTTP 200` with the full store
object for `storeId=7` ("ANDALOS-WH", `cityId=31`, `areaId=8952`,
`promiseTime=45`) - a **different** store than the Jeddah Pickup test
resolved (`storeId=97`), exactly as expected since each channel resolves
its own nearest/best-fit branch independently. (A first attempt at the
same coordinate as the Pickup test, `21.55662781, 39.17014248`, was
**not** deliverable - consistent with the "reverse-geocoding is not
perfectly deterministic per exact point" observation above; the nearby
`ANDALOS-WH`-area coordinate resolved successfully on the first try.)

**`menuConfigId`/`clusterId` again resolved to the IDENTICAL
`HRD_SA_23`/`1_8`** as both the Riyadh delivery branch AND the Jeddah
Pickup branch. Every one of 40+ sampled products' prices/offers matched
the Riyadh baseline exactly, and matched the Jeddah Pickup run's own
values exactly too - see `../api-map/api-map.md` "Channel separation
mechanism" update. Raw evidence (git-ignored) and its sanitized copy live
under `raw/<timestamp>/` and `sanitized/jeddah-branch/` respectively.

## What was NOT done (by design)

- Never filled in street/building/floor/flat or clicked "Continue" on the
  address-details form (would create/save an address) - on either branch
  tested.
- Never logged in to use a saved address (the modal's own "LOGIN" button
  was never clicked).
- Never placed an order, never reached a delivery-fee/minimum-order
  screen (those only appear once a cart has items - out of scope; see
  `../api-map/unresolved-items.md` "Delivery fees" - still unresolved
  after the second branch too).
