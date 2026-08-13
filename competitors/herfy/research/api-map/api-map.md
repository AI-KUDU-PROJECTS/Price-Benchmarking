# Herfy (`order.herfy.com`) API map

Herfy's online-ordering storefront runs on **Solo** (`getsolo.io` /
`api.solo.skylinedynamics.com`), a third-party ordering SaaS platform - a
Nuxt.js server-rendered storefront in front of a REST API and a set of
static, CDN-hosted menu JSON files. This is a completely different
platform family from KFC's own backend or Burger King's RBI/Sanity stack.

**Everything below is fully public/unauthenticated** except for one
non-sensitive header (`solo-app`) that is embedded directly in every
page's own HTML - not a login, not a session cookie, not a secret.

## How this was verified

Live headless-browser recon against
`https://order.herfy.com/menu/-193160`, recording every network request
and dumping the page's embedded `window.__NUXT__` client state, then
independently re-verifying the key findings with plain, cookie-less
`curl`/`https.request()` calls (no browser at all):

- `curl https://order.herfy.com/menu/-193160` → `200 OK`, and the raw HTML
  does contain the full rendered menu text (Arabic, with real prices) -
  confirmed a browser is not strictly required to reach the content, only
  to reliably *parse* it (see below).
- `curl https://cdn.getsolo.io/apps/production/PM6OEiBo83O-menu-12303.json`
  → `200 OK`, a clean, well-structured JSON (no HTML/JS wrapping at all) -
  this is the collector's primary data source.
- `curl -H "solo-app: jRKV7Ol8nV3O9hmp" https://api.solo.skylinedynamics.com/locations?_lat=...&_long=...&limit=999`
  → `200 OK`, 361 real branches nationwide.
- `curl -H "solo-app: jRKV7Ol8nV3O9hmp" https://api.solo.skylinedynamics.com/locations/29696`
  → `200 OK`, real single-branch data.

One real quirk found only by doing this live:

- **`window.__NUXT__` is not JSON.** It is assigned via a minified IIFE
  with webpack/Nuxt-style string-literal deduplication
  (`(function(a,b,c,...){ ...; return {...} })(x,y,z,...)`) - a plain
  regex-extract-then-`JSON.parse()` on the raw HTML does **not** work; the
  expression must actually be evaluated by a JS engine. `api.solo.
  skylinedynamics.com/applications/{id}` looked like a shortcut to get the
  same settings (`key`/`menu-ref`) without a browser, but returned `401`
  when tried standalone with only the `solo-app` header - so this
  collector keeps a **minimal**, one-time-per-run Playwright bootstrap
  step (`api-bootstrap.js`, matching KFC's own bootstrap pattern) whose
  only job is `page.goto()` + `page.evaluate(() => window.__NUXT__)`. No
  interaction/clicking happens in it at all.

## Branch / channel model

- **Order types**: `to-go` (= **PICKUP**) and `deliver` (= **DELIVERY**),
  from `state.app.settings.attributes['allowed-order-types']`.
- **The menu is not branch- or order-type-scoped.** `menu-ref`'s CDN JSON
  is one static file with no request parameters - the same 144 items and
  prices are returned regardless of which branch or order type is
  selected. Channel availability lives entirely at the **branch** level
  (`locationsNearby`/`locationById`'s `pickup-enabled`/`delivery-enabled`
  and `is-open-pickup`/`is-open-deliver` fields) and, per-item, in two
  always-present-but-unset-at-verification flags
  (`disable-for-pickup`/`disable-for-delivery`, both `0` on every one of
  the 144 sampled items).

## Branch selection

**RUH - Al Mogarazat - Eirad Plaza Mall 1073 (locationId `29696`)** is
used as the default configured branch: confirmed live via
`GET /locations/29696` to have `status="active"`, `is-open=true`,
`is-open-pickup=true`, `is-open-deliver=true`, `pickup-enabled=1`,
`delivery-enabled=1` at verification time (2026-08-11). Any other branch
from the same nearby-search response with both flags enabled and
currently open would also work (128 such candidates were found within the
361-branch nearby search used during verification).

## Endpoints

### `GET https://order.herfy.com/menu/-193160` - app bootstrap (SSR page)

Not a JSON API - a full HTML page. This collector's `api-bootstrap.js`
loads it once per run with Playwright and reads two things out of
`window.__NUXT__.state.app.settings.attributes`:

- `key` - the **App Key**, sent as the `solo-app` header on every
  subsequent direct HTTPS call. Confirmed live as `jRKV7Ol8nV3O9hmp` - a
  static, non-sensitive, per-application identifier, not a per-session
  token (present verbatim, unchanged, in every fresh page load).
- `menu-ref` - a direct CDN URL to the current menu JSON (see below). Read
  fresh each run rather than hardcoded, in case Herfy republishes the
  menu under a new file/id (`default-menu-id` at verification time: `12303`).

Also available from the same bootstrap (`window.__NUXT__.state.concept.concept`):
concept-level metadata (`currency-code: "SAR"`, `vat-rate: 15`,
`vat-type: "inclusive"`, bilingual concept name) - stored for reference,
not required for pricing (VAT is already inclusive in every `price`
value observed).

### `GET <menu-ref CDN URL>` (`cdn.getsolo.io`) - the full menu

```
https://cdn.getsolo.io/apps/production/PM6OEiBo83O-menu-12303.json   (at verification time - re-read fresh, see above)
```

Plain static JSON, no auth, no query parameters. Response:
`data[]` - one entry per category (`type: "category-items"`), each
carrying its own `attributes.category` (bilingual name, image, enabled
flag) and `attributes.items[]` (the products: bilingual name/description,
**real** `price`/`list-price`/`original-price`, `calorie-count`,
`is-combo`, `disable-for-pickup`/`disable-for-delivery`, and a
`modifier-groups[]` reference list). `included.modifierGroups[]` /
`included.modifiers[]` resolve those references into real names and
**real per-modifier price deltas** (e.g. "Add Cheese" = +1 SAR - confirmed
live: 260 of 445 modifiers carry a nonzero price).

Confirmed live: **14 categories, 144 items, 340 modifier groups, 445
modifiers**.

#### Known limitation: no before/after discount signal

Every one of the 144 items has `list-price: 0` and `price ==
original-price`, with zero exceptions (confirmed by iterating the full
response). This is true even for the 10 items in the "Offers" category
(see below) - so, exactly like Burger King's "KING DAILY DEALS",
**presence in the "Offers" category is a real, CMS-declared merchandising
signal, but it is not itself a discount amount** - `special_price`,
`discount_amount`, and `discount_percentage` are still always `NULL` for
every product, including these.

### `GET /locations?_lat={lat}&_long={long}&limit=999` (`api.solo.skylinedynamics.com`)

Requires the `solo-app` header (returns `400 "Concept Key and App Key are
missing"` without it). Finds every branch near a coordinate. Confirmed
live: 361 real branches nationwide for a central-Riyadh search, each with
real name/coordinates/hours/`pickup-enabled`/`delivery-enabled`/
`is-open-pickup`/`is-open-deliver`.

### `GET /locations/{locationId}` (`api.solo.skylinedynamics.com`)

Same auth requirement. Single-branch lookup - the branch-existence and
channel-availability check for the one fixed configured branch. Confirmed
live for locationId `29696`.

## Deal category

**"Offers" (English) / "عروض حصرية" (Arabic)** - categoryId `169347` at
verification time, 10 items, every one a combo (`is-combo: true`, e.g.
"Double Offer", "Gathering Offer", "Fun Offer - Spicy"). This is the most
directly-named offer signal found across any competitor in this repo so
far (KFC has no equivalent category; Burger King's closest analog,
"KING DAILY DEALS", had to be inferred and confirmed, not read literally
off an English category label). `backend/offer_parser.py` uses category
membership in this one category as this brand's offer signal - see
"Known limitation: no before/after discount signal" above for what is
still never fabricated even for these.

## Schema validation

`collector/api-client.js`'s `schemaCheck()` (same pattern as every other
competitor in this repo) requires: `menu-ref` response → `data` is an
array and `included` is an object with `modifierGroups`/`modifiers`
arrays; `locations`/`locations/{id}` → `data` is present (array or
object, depending on which of the two endpoints).

## What is never recorded here (or anywhere in git)

- No login/account credentials - browsing the menu and checking branch
  availability never requires login on this brand's storefront.
- No real phone number, payment detail, or delivery address - this
  collector never requests `/checkout/`, `/payment/`, or `/user/` (all
  three disallowed by `robots.txt` anyway) and never adds anything to a
  cart.
- No cookies or session tokens are saved to disk or git - the `solo-app`
  header value lives only in memory for the duration of one run.
