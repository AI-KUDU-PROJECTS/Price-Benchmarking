#!/usr/bin/env node
'use strict';

/**
 * crawl-kfc.js
 * ---------------------------------------------------------------------
 * Main entry point. Launches Chromium, starts HAR recording BEFORE any
 * navigation happens, drives the delivery -> menu -> product -> cart ->
 * checkout flows in sequence, and guarantees the HAR + all JSON output
 * files are written even on error, Ctrl+C, or an unrecoverable page
 * failure.
 *
 * Run with: node crawl-kfc.js
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

// Minimal, dependency-free .env loader (keeps this security-sensitive
// project to zero third-party runtime dependencies besides Playwright
// itself). Existing process.env values always win over the .env file.
function loadDotEnvFile(filePath) {
  let content;
  try {
    content = fs.readFileSync(filePath, 'utf8');
  } catch (e) {
    return; // no .env file present - defaults from config.js apply
  }
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}
loadDotEnvFile(path.join(__dirname, '.env'));

const CONFIG = require('../collector/config');
const logger = require('../collector/logger');
const urlUtils = require('../collector/url-utils');
const safe = require('../collector/safe-actions');
const deliveryFlow = require('./delivery-flow');
const menuCrawler = require('./menu-crawler');
const cartFlow = require('./cart-flow');
const checkoutFlow = require('./checkout-flow');

const DESKTOP_USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

function createDataStore() {
  return {
    _startedAt: new Date().toISOString(),
    visitedPages: [],
    failedPages: [],
    discoveredUrls: [],
    menuCategories: [],
    menuProducts: [],
    productOptions: [],
    deliveryInformation: {
      testLocation: CONFIG.TEST_LOCATION,
      deliveryAvailable: null,
      availableRestaurant: null,
      branchId: null,
      branchName: null,
      estimatedDeliveryTime: null,
      deliveryFee: null,
      minimumOrder: null,
      serviceFee: null,
      addressValidationResult: null,
      apiEndpointSource: null,
      validationAttempts: [],
      unavailableAttempts: [],
      lastUnavailableMessage: null,
      pickupProbed: false,
    },
    restaurantAvailability: [],
    cartCalculations: {},
    checkoutInformation: {},
    networkErrors: [],
    cartState: { representativeProduct: null },
    // Internal (not written to disk directly): rolling buffers used to
    // cross-reference DOM-scraped data against real API JSON payloads.
    _rawMenuApiResponses: [],
    _lastMenuApiUrl: null,
    _lastCartApiUrl: null,
    _checkoutApiUrls: [],
  };
}

// --- Network response classification -----------------------------------
// Real endpoint names confirmed by live inspection while building this
// project: /api/validateLocation, /api/getStoreList, /api/getMenu,
// /api/getMenuConfig (all first-party on saudi.kfc.me). Everything else is
// a best-effort keyword guess so the crawler still copes if the site adds
// or renames endpoints.

const FEE_PATTERNS = [/deliveryfee/i, /delivery_fee/i];
const MIN_ORDER_PATTERNS = [/minorder/i, /minimumorder/i, /min_order/i, /minimumcartvalue/i, /minimumbasket/i];
const SERVICE_FEE_PATTERNS = [/servicefee/i, /service_fee/i];
const ETA_PATTERNS = [/\beta\b/i, /estimated.*time/i, /deliverytime/i, /delivery_time/i];

function classifyApiUrl(rawUrl) {
  const url = rawUrl.toLowerCase();
  if (url.includes('validatelocation')) return 'validateLocation';
  if (url.includes('getstorelist') || url.includes('storelist')) return 'storeList';
  if (url.includes('getmenuconfig')) return 'menuConfig';
  if (url.includes('getmenu')) return 'menu';
  if (url.includes('cart') || url.includes('basket')) return 'cart';
  if (url.includes('checkout')) return 'checkout';
  if (url.includes('coupon') || url.includes('promo')) return 'promotion';
  if (url.includes('payment')) return 'payment';
  if (url.includes('categ')) return 'category';
  if (url.includes('branch') || url.includes('store') || url.includes('outlet')) return 'branch';
  if (url.includes('login') || url.includes('auth') || url.includes('otp')) return 'auth';
  return 'other';
}

function attachNetworkRecorder(page, dataStore) {
  page.on('requestfailed', (req) => {
    const failure = req.failure();
    dataStore.networkErrors.push({
      url: req.url(),
      method: req.method(),
      status: null,
      error: failure ? failure.errorText : 'unknown',
      timestamp: new Date().toISOString(),
    });
  });

  page.on('response', async (res) => {
    try {
      const request = res.request();
      const url = res.url();
      const status = res.status();
      const contentType = res.headers()['content-type'] || '';

      if (status >= 400) {
        dataStore.networkErrors.push({ url, method: request.method(), status, error: null, timestamp: new Date().toISOString() });
      }
      if (!contentType.toLowerCase().includes('json')) return;

      let body;
      try {
        body = await res.json();
      } catch (e) {
        return; // not actually parsable JSON (e.g. empty body) - nothing more to classify
      }

      const kind = classifyApiUrl(url);
      const timestamp = new Date().toISOString();
      const info = dataStore.deliveryInformation;

      if (kind === 'validateLocation') {
        info.validationAttempts.push({ status, timestamp, message: body && body.message });
        info.apiEndpointSource = url;
        if (status === 200 && body && body.data) {
          const store = body.data.store || body.data;
          info.deliveryAvailable = true;
          info.availableRestaurant = store;
          info.branchId = store.storeId ?? store.id ?? null;
          info.branchName = store.name_en || store.name || null;
          info.addressValidationResult = body;
          info.estimatedDeliveryTime = urlUtils.firstByKeyPattern(body, ETA_PATTERNS);
          info.deliveryFee = urlUtils.firstByKeyPattern(body, FEE_PATTERNS);
          info.minimumOrder = urlUtils.firstByKeyPattern(body, MIN_ORDER_PATTERNS);
          info.serviceFee = urlUtils.firstByKeyPattern(body, SERVICE_FEE_PATTERNS);
        } else if (status >= 400) {
          if (info.deliveryAvailable !== true) info.deliveryAvailable = false;
          info.lastUnavailableMessage = (body && body.message) || `HTTP ${status}`;
          info.unavailableAttempts.push({ status, message: info.lastUnavailableMessage, timestamp });
          logger.warn(`[LOCATION] Unavailable location response: ${info.lastUnavailableMessage}`);
        }
      } else if (kind === 'storeList') {
        dataStore.restaurantAvailability.push({ source: url, timestamp, raw: (body && body.data) || body });
      } else if (kind === 'menu' || kind === 'menuConfig') {
        dataStore._lastMenuApiUrl = url;
        dataStore._rawMenuApiResponses.push({ url, status, timestamp, body });
        if (dataStore._rawMenuApiResponses.length > 6) dataStore._rawMenuApiResponses.shift();
      } else if (kind === 'cart') {
        dataStore._lastCartApiUrl = url;
      } else if (kind === 'checkout' || kind === 'payment') {
        dataStore._checkoutApiUrls.push(url);
        if (dataStore._checkoutApiUrls.length > 25) dataStore._checkoutApiUrls.shift();
      }
    } catch (e) {
      // Network classification must never crash the crawl.
    }
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') logger.tag('CONSOLE', `Page console error: ${msg.text().slice(0, 300)}`);
  });
  page.on('pageerror', (err) => {
    logger.tag('PAGEERROR', `Uncaught page error: ${err.message}`);
  });
}

async function recordVisit(page, dataStore, extra = {}) {
  dataStore.visitedPages.push({
    url: page.url(),
    title: await page.title().catch(() => null),
    timestamp: new Date().toISOString(),
    ...extra,
  });
}

/**
 * Supplementary breadth-first pass over same-domain links discovered via
 * a[href]/link[href] (nav, footer, product/category cards already visited
 * by the scripted flows are naturally excluded via the visited tracker).
 * This ALWAYS respects robots.txt, independent of RESPECT_ROBOTS_TXT,
 * because ambient link-following is exactly what robots.txt governs.
 */
const ASSET_EXTENSION_RE = /\.(js|css|png|jpe?g|svg|ico|json|woff2?|ttf|map|gz|webp|mp4|pdf)(\?|$)/i;

async function runUrlDiscoveryPass(page, dataStore, robots, tracker) {
  logger.section('URL DISCOVERY');
  const base = page.url();
  const links = await urlUtils.extractLinksFromPage(page, base);
  const toVisit = [];
  for (const link of links) {
    dataStore.discoveredUrls.push({ url: link, source: base, timestamp: new Date().toISOString() });
    if (tracker.has(link)) continue;
    if (!urlUtils.isAllowedDomain(link)) continue;
    if (ASSET_EXTENSION_RE.test(link)) continue; // recorded above, but not worth a full page navigation
    if (urlUtils.isRobotsDisallowed(link, robots.matchers)) {
      logger.tag('ROBOTS', `Skipping disallowed discovered URL: ${link}`);
      continue;
    }
    toVisit.push(link);
  }
  logger.tag('DISCOVERY', `Discovered ${links.length} link(s) on ${base}; ${toVisit.length} are new and allowed to visit`);

  const remainingBudget = Math.max(0, CONFIG.MAX_PAGES - dataStore.visitedPages.length);
  const budget = Math.min(toVisit.length, remainingBudget, 40); // keep the supplementary pass modest and polite
  for (let i = 0; i < budget; i++) {
    const url = toVisit[i];
    tracker.add(url);
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT });
      await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
      await recordVisit(page, dataStore, { depth: 1, discovered: true });
      logger.tag('VISIT', `[${i + 1}/${budget}] ${url}`);
    } catch (e) {
      dataStore.failedPages.push({ url, reason: e.message, timestamp: new Date().toISOString() });
      logger.error(`[VISIT] Failed to load ${url}: ${e.message}`);
    }
  }
  if (toVisit.length > budget) {
    logger.tag('DISCOVERY', `Not visiting ${toVisit.length - budget} further discovered URL(s) this run (kept the supplementary pass bounded/polite)`);
  }
}

function writeJson(filePath, data) {
  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
  } catch (e) {
    logger.error(`Failed to write ${filePath}: ${e.message}`);
  }
}

function buildSummary(dataStore, stopReason) {
  return {
    startedAt: dataStore._startedAt,
    finishedAt: new Date().toISOString(),
    stopReason,
    startUrl: CONFIG.START_URL,
    harPath: CONFIG.HAR_PATH,
    respectRobotsTxt: CONFIG.RESPECT_ROBOTS_TXT,
    pagesVisited: dataStore.visitedPages.length,
    pagesFailed: dataStore.failedPages.length,
    urlsDiscovered: dataStore.discoveredUrls.length,
    categoriesFound: dataStore.menuCategories.length,
    productsFound: dataStore.menuProducts.length,
    productOptionRows: dataStore.productOptions.length,
    deliveryAvailable: dataStore.deliveryInformation.deliveryAvailable,
    branchName: dataStore.deliveryInformation.branchName,
    cartSkipped: !!(dataStore.cartCalculations && dataStore.cartCalculations.skipped),
    checkoutSkipped: !!(dataStore.checkoutInformation && dataStore.checkoutInformation.skipped),
    checkoutStoppedAt: dataStore.checkoutInformation && dataStore.checkoutInformation.stoppedAt,
    networkErrorsRecorded: dataStore.networkErrors.length,
  };
}

function writeAllOutputs(dataStore, summary) {
  writeJson(CONFIG.FILES.VISITED_PAGES, dataStore.visitedPages);
  writeJson(CONFIG.FILES.FAILED_PAGES, dataStore.failedPages);
  writeJson(CONFIG.FILES.DISCOVERED_URLS, dataStore.discoveredUrls);
  writeJson(CONFIG.FILES.MENU_CATEGORIES, dataStore.menuCategories);
  writeJson(CONFIG.FILES.MENU_PRODUCTS, dataStore.menuProducts);
  writeJson(CONFIG.FILES.PRODUCT_OPTIONS, dataStore.productOptions);
  writeJson(CONFIG.FILES.DELIVERY_INFORMATION, dataStore.deliveryInformation);
  writeJson(CONFIG.FILES.RESTAURANT_AVAILABILITY, dataStore.restaurantAvailability);
  writeJson(CONFIG.FILES.CART_CALCULATIONS, dataStore.cartCalculations);
  writeJson(CONFIG.FILES.CHECKOUT_INFORMATION, dataStore.checkoutInformation);
  writeJson(CONFIG.FILES.NETWORK_ERRORS, dataStore.networkErrors);
  writeJson(CONFIG.FILES.CRAWL_SUMMARY, summary);
  logger.section('OUTPUT FILES WRITTEN');
}

async function main() {
  logger.init();
  logger.section('KFC SAUDI HAR CRAWLER STARTING');
  logger.info(`START_URL=${CONFIG.START_URL}`);
  logger.info(`HAR_PATH=${CONFIG.HAR_PATH}`);
  logger.info(`HEADLESS=${CONFIG.HEADLESS}`);
  logger.info(`RESPECT_ROBOTS_TXT=${CONFIG.RESPECT_ROBOTS_TXT}`);
  logger.info(`Test location: ${JSON.stringify(CONFIG.TEST_LOCATION)}`);

  const dataStore = createDataStore();
  const tracker = urlUtils.createUrlTracker();

  let origin;
  try {
    origin = new URL(CONFIG.START_URL).origin;
  } catch (e) {
    origin = 'https://saudi.kfc.me';
  }

  const matchers = await urlUtils.loadRobotsMatchers(origin, logger);
  const robots = {
    respect: CONFIG.RESPECT_ROBOTS_TXT,
    matchers,
    blocksCart: urlUtils.robotsBlocksKeyword(matchers, 'cart'),
    blocksCheckout: urlUtils.robotsBlocksKeyword(matchers, 'checkout') || urlUtils.robotsBlocksKeyword(matchers, 'singlepagecheckout'),
    blocksRegistration: urlUtils.robotsBlocksKeyword(matchers, 'regist'),
    blocksNotification: urlUtils.robotsBlocksKeyword(matchers, 'notif'),
  };
  logger.tag(
    'ROBOTS',
    `RESPECT_ROBOTS_TXT=${robots.respect} | cart blocked=${robots.blocksCart} | checkout blocked=${robots.blocksCheckout} | registration blocked=${robots.blocksRegistration}`
  );

  // --- Browser / context setup: HAR recording MUST start before any navigation ---
  // handleSIGINT/handleSIGTERM/handleSIGHUP are explicitly disabled here:
  // Playwright's own default signal handlers race with (and can win
  // against) our custom shutdown() below, killing the browser/process
  // before the HAR and JSON output files finish writing. This was caught
  // during development testing (Ctrl+C produced a truncated HAR) - our own
  // process.on('SIGINT'/'SIGTERM') handlers further down are the only ones
  // that should run.
  const browser = await chromium.launch({
    headless: CONFIG.HEADLESS,
    handleSIGINT: false,
    handleSIGTERM: false,
    handleSIGHUP: false,
  });
  const context = await browser.newContext({
    recordHar: { path: CONFIG.HAR_PATH, mode: 'full', content: 'embed' },
    ignoreHTTPSErrors: true,
    geolocation: { latitude: CONFIG.TEST_LOCATION.latitude, longitude: CONFIG.TEST_LOCATION.longitude },
    permissions: ['geolocation'],
    viewport: { width: 1440, height: 960 },
    userAgent: DESKTOP_USER_AGENT,
    locale: 'en-US',
  });
  context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
  context.setDefaultNavigationTimeout(CONFIG.PAGE_TIMEOUT);
  // Explicit grant per the spec, in addition to the `permissions` context option above.
  await context.grantPermissions(['geolocation'], { origin }).catch(() => {});

  let shuttingDown = false;
  let stopReason = 'completed normally';

  async function shutdown(reason) {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.section(`SHUTTING DOWN: ${reason}`);
    const summary = buildSummary(dataStore, reason);
    writeAllOutputs(dataStore, summary);
    try {
      await context.close(); // flushes the HAR file to disk - required by Playwright
      logger.success(`[HAR] Saved to ${CONFIG.HAR_PATH}`);
    } catch (e) {
      logger.error(`Error closing context: ${e.message}`);
    }
    try {
      await browser.close();
    } catch (e) {
      logger.error(`Error closing browser: ${e.message}`);
    }
    // Observed during testing: calling process.exit() immediately after
    // context.close() resolves can still race ahead of the last bytes of
    // the HAR file being flushed to disk, truncating it. A short grace
    // pause here costs a fraction of a second and closes that window.
    await new Promise((resolve) => setTimeout(resolve, 500));
    logger.close(reason);
  }

  let signalCount = 0;
  const onSignal = (sig) => {
    signalCount += 1;
    if (signalCount >= 2) {
      logger.error(`[SIGNAL] Second ${sig} received - forcing immediate exit (HAR from this run may be incomplete)`);
      process.exit(1);
      return;
    }
    logger.warn(`[SIGNAL] Received ${sig} - saving HAR and output files before exit (press Ctrl+C again to force-quit)`);

    // Anchor the event loop for the duration of the graceful shutdown.
    // Without a real pending handle here, Node can decide the event loop is
    // "empty" (once the crawl action in flight when the signal arrived
    // rejects) and terminate the process mid-shutdown, abandoning this
    // shutdown() call before context.close() finishes flushing the HAR to
    // disk. This was observed (and the HAR came out truncated) during
    // development testing - do not remove this without re-testing Ctrl+C.
    const keepAlive = setInterval(() => {}, 1000);
    const forceExitTimer = setTimeout(() => {
      logger.error('[SIGNAL] Graceful shutdown took too long - forcing exit');
      process.exit(1);
    }, 20000);

    shutdown(`interrupted by ${sig}`)
      .catch((e) => logger.error(`[SIGNAL] Error during shutdown: ${e.message}`))
      .finally(() => {
        clearInterval(keepAlive);
        clearTimeout(forceExitTimer);
        process.exit(0);
      });
  };
  process.on('SIGINT', () => onSignal('SIGINT'));
  process.on('SIGTERM', () => onSignal('SIGTERM'));

  const page = await context.newPage();
  attachNetworkRecorder(page, dataStore);

  try {
    logger.section('HOMEPAGE');
    await safe.retry(
      () => page.goto(CONFIG.START_URL, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT }),
      CONFIG.MAX_RETRIES,
      logger,
      'load homepage'
    );
    // This is a client-rendered SPA - domcontentloaded fires long before the
    // header/cookie-banner/product cards actually exist in the DOM. Wait for
    // a concrete readiness signal instead of a fixed sleep (spec: "Avoid
    // relying only on networkidle" / "Use configurable timeouts").
    await page
      .waitForSelector(
        'button:has-text("ACCEPT"), [role="tablist"], button:has-text("ADD TO CART"), [class*="gotItButton" i]',
        { timeout: CONFIG.PAGE_TIMEOUT }
      )
      .catch(() => logger.warn('[HOMEPAGE] Page did not show expected ready-state elements in time - continuing anyway'));
    await page.waitForTimeout(1000);
    await recordVisit(page, dataStore, { depth: 0 });
    tracker.add(urlUtils.normalizeUrl(page.url(), page.url()) || page.url());

    // Cookie/promo overlays can appear in more than one wave; a couple of
    // passes with a short settle in between catches sequential popups.
    for (let i = 0; i < 3; i++) {
      const dismissed = await safe.dismissOverlays(page, logger);
      await page.waitForTimeout(700);
      if (!dismissed) break;
    }
    await safe.scrollGradually(page, 3, 300);

    await deliveryFlow.runDeliveryFlow(page, context, logger, dataStore);
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

    await deliveryFlow.runPickupFlow(page, context, logger, dataStore).catch((e) => {
      if (e instanceof safe.SafetyBlockedError) throw e;
      logger.warn(`[DELIVERY] Pickup probe failed: ${e.message}`);
    });
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

    await menuCrawler.crawlMenu(page, context, logger, dataStore, robots);
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

    await cartFlow.runCartFlow(page, context, logger, dataStore, robots);
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

    await checkoutFlow.runCheckoutFlow(page, context, logger, dataStore, robots);
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

    await runUrlDiscoveryPass(page, dataStore, robots, tracker).catch((e) => logger.warn(`[DISCOVERY] ${e.message}`));

    stopReason = 'completed all flows';
  } catch (e) {
    if (shuttingDown) {
      // Ctrl+C (or a signal) already started tearing the browser down while
      // this action was in flight - the resulting "context closed" error is
      // expected noise, not a real crash. Don't overwrite stopReason, don't
      // try to screenshot an already-closed page.
      logger.tag('SHUTDOWN', `In-flight action ended because shutdown was already in progress: ${e.message}`);
    } else if (e instanceof safe.SafetyBlockedError) {
      stopReason = `safety guard triggered: ${e.message}`;
      logger.warn(`[SAFETY] Stopping crawl early because of a safety guard: ${e.message}`);
    } else {
      stopReason = `error: ${e.message}`;
      logger.error(`[CRASH] ${e.stack || e.message}`);
      dataStore.failedPages.push({ url: page.url(), reason: e.message, timestamp: new Date().toISOString() });
      await safe.captureFailure(page, logger, 'top-level-error').catch(() => {});
    }
  } finally {
    await shutdown(stopReason);
  }
}

main().catch((e) => {
  console.error('[FATAL]', e);
  process.exit(1);
});
