# Legacy: full-journey HAR crawler

This folder holds the project's **original** artifact: a Playwright-based,
DOM-scraping, full-user-journey crawler (delivery/pickup selection, menu
browsing, cart, checkout) that recorded everything into a HAR file plus a
set of one-shot JSON exports. It has been superseded by the API-first daily
monitoring system now at the project root (`collector/`, `backend/`,
`app.py`, `run_collector.py`, `scheduler.py`) - see the root `README.md`.

Nothing here is deleted because:

- `crawl-kfc.js`, `delivery-flow.js`, `menu-crawler.js`, `product-crawler.js`
  were the primary source used to identify the real API endpoints
  (`validateLocation`, `getStoreList`, `getMenuConfig`, `getMenu`) that the
  new system's `collector/api-client.js` calls directly.
- `cart-flow.js` / `checkout-flow.js` are kept for reference only - the new
  system never adds to cart or checks out (not needed for price/offer
  monitoring; see root README "Security & compliance").
- `kfc-saudi-complete-flow.har` (and its `*.json` siblings) is the actual
  captured network traffic used to reverse-engineer the API schema
  documented in `../api-map.json` / `../api-map.md`.

**These files are not run by the new system and are not maintained going
forward.** The safety-guard module they depended on (`safe-actions.js`,
`config.js`, `logger.js`, `url-utils.js`) was moved to `../collector/` and
**reshaped** for the new system (new field names, new directories, the
full-journey-specific config like `MAX_PAGES`/`TEST_LOCATION`/`HAR_PATH`
was removed since the new architecture doesn't need it). The safety guard
itself (`FINAL_ACTION_PATTERNS`, `SENSITIVE_FIELD_PATTERNS`, the fail-closed
click guard) is preserved verbatim and is still the single choke point for
every click the new `collector/screenshot-capture.js` module performs.

Their `require('./config')` / `require('./safe-actions')` / etc. calls were
repointed at `../collector/...` so they still resolve, but because that
module's shape changed, **the legacy scripts here are not guaranteed to run
end-to-end as-is** - they are kept for provenance (how the real API
endpoints were identified) and for the safety-guard pattern, not as a
maintained tool. If you actually need the old full-journey HAR crawl, treat
this folder as a reference implementation and restore the fields it expects
in a local copy of `config.js` rather than running it against the shared one.
