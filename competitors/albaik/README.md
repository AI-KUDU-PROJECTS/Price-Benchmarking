# ALBAIK app collection

The official Android app (`com.albaik.customer`, verified with version 9.32)
provides pickup and delivery menus. Pickup selects **Arubah, Riyadh**, the
Albaik branch on Al Orubah Road in Olaya. Delivery uses the app's location checker
at a nearby point (24.70265, 46.65075); the app must confirm coverage before any
prices are accepted. No order is submitted and no products are added to a cart.

## Server setup

Install ALBAIK from [Google Play](https://play.google.com/store/apps/details?id=com.albaik.customer)
on the Android emulator. Grant precise location access and use the app in English.
Install the official [Appium Settings helper](https://github.com/appium/io.appium.settings)
and grant it fine/coarse location permissions. Its mock-location foreground
service supplies continuous GPS/fused locations to the app. The collector
sets that service to the configured nearby point for each run.

The service defaults to `android-emulator.service`, device `emulator-5554`.
`ALBAIK_EMULATOR_SERVICE`, `ALBAIK_ADB_SERIAL`, `ALBAIK_LATITUDE`, and
`ALBAIK_LONGITUDE` override these values. The pickup branch remains explicitly
verified as Arubah, regardless of GPS configuration.

## Run

```bash
python manage.py collect albaik-app --channel PICKUP
python manage.py collect albaik-app --channel DELIVERY
```

To resume a recent interrupted collection, add
`--resume competitors/albaik/data/raw/<run>/progress.json`. The progress must
be less than one hour old and match the selected channel and configured
coordinates. The collector verifies the location again, revisits the menu,
and skips only products already fully read. The final capture records the
progress file used.

Market Overview has an independent **Albaik App Collection** button. It queues
pickup then delivery, records each status and failure reason, and refreshes
its data on completion. Finished channel statuses come from their latest recorded
app runs, including CLI runs. Its state is separate from HungerStation.
The daily Market Overview schedule runs websites, then HungerStation, then
this app's pickup and delivery collection. Set `AUTO_PULL_ALBAIK_APP=false`
to omit the official app from the schedule. The manual button sits beside
the website and HungerStation collection buttons at the top of the page.

Both collectors share the existing emulator lock. A run starts the emulator,
verifies the selected channel/location, traverses every category and checks the
All tab, then stops the emulator. Product detail pages supply observed prices,
descriptions, calories, regular/spicy products, and each available juice size.
Sizes are separate product rows with their observed price and volume. Add-ons
are not combined into invented product variants.

## Data and images

- `data/database/albaik_monitor.db`: independent official-app snapshots/history.
- `data/raw/<run>/`: screen XML, capture JSON or failure details and screenshot.
  `progress.json` is updated atomically after every verified product, so a later
  failure does not discard already-read details. It is explicitly incomplete;
  only the final validated capture becomes the displayed menu.
- `data/images/`: product photos cropped from the app's detail image, served under
  `/albaik-app-images/`. Files use a stable product-name key shared by both
  channels and variants. An existing image is reused before taking a screenshot;
  only a new product (or a missing local image) causes image capture.

A snapshot must finish traversal, contain at least 10 products with unique
identities, valid prices and images, and not lose over 20% of the previous
channel's product count. A failed attempt records the reason while preserving
the last successful menu. Pickup and delivery prices/history remain separate.
The HungerStation source remains available independently through the shared
brand adapter.

The app exposes product names rather than stable API IDs in its accessibility
tree, so renaming a product creates a new identity/photo. Menu availability can
vary by time and channel. Layout or language changes fail explicitly and retain
the previous snapshot instead of silently accepting a partial menu.

## Live verification, 2026-11-02

Pickup completed with 99 product/variant rows across 66 base products and all
seven categories. The repeat run reused all 66 saved photos without modifying
them. Opening `BAIKEEZ Burger with Lahaleebo Sauce` in Delivery remained on a
blank loading screen at two nearby delivery points. At the user's explicit
request, that exact product is now excluded from Delivery in
`app_config.EXCLUDED_PRODUCTS`. Pickup continues to include it. A completed
capture lists the encountered exclusions, and Market Overview shows them with
the result. The user also approved continuing past other Delivery product
pages that do not open after two attempts. `SKIP_UNREADABLE_CHANNELS` enables
this for Delivery only. Each such name and reason is saved in
`unreadable_products` and shown with the result. A finished run covers the
traversed menu subject to these reported exceptions. Products that did open
still require verified prices, options, and images; parsing failures are not
silently skipped. Pickup keeps its stricter failure behavior.

An Android "isn't responding" dialog is waited once. If it persists during
location selection, navigation restarts the app once before reporting failure.

The Delivery promotion carousel can keep Android's accessibility reader from
reaching idle, even though the menu is visible. Before discovering categories,
the collector scrolls the promotion offscreen without trying to read the
intermediate animated view. It then uses the pinned category tabs and gently
aligns each category's first row without returning to the banner. Reader failures
include Android's original error and the collection stage in the saved result.

The verified Delivery collection completed with **96 product/variant rows
across 63 base products**. Besides the explicitly excluded burger, the app
could not open Tahina Sauce, Tartar Sauce, and Water after two attempts; these
three names are reported with the successful result. Berain water was read
normally. The API serves 99 Pickup rows, 96 Delivery rows, and the existing
82 HungerStation rows independently. All 66 stored photos were reused without
modification. The delivery capture is `albaik-app-delivery-ad6a11acbe48`.
