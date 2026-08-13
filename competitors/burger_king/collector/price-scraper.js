'use strict';

/**
 * collector/price-scraper.js
 * ---------------------------------------------------------------------
 * Extracts live per-item prices by reading the rendered `/en/menu` page's
 * visible text, once a store is selected for the given channel.
 *
 * WHY THIS EXISTS: see research/api-map/api-map.md "Known limitation:
 * live prices" - no price field exists anywhere in the GetMenuSections
 * API response (confirmed by exhaustively grepping the full response),
 * yet real prices ARE rendered on the page once a store is chosen. This
 * module is the deliberately-documented, pragmatic way this collector
 * still gets real prices, rather than guessing at an unconfirmed
 * endpoint or shipping the tool with every price blank. It is the one
 * place in this collector that deviates from the pure-API architecture
 * used for everything else (branch verification, delivery availability,
 * menu structure).
 *
 * Every click funnels through safe-actions.js exactly like
 * screenshot-capture.js - this module drives a real browser page and
 * must never be able to place an order or submit a form.
 * ---------------------------------------------------------------------
 */

const { chromium } = require('playwright');
const CONFIG = require('./config');
const safe = require('./safe-actions');

function normalizeName(s) {
  return (s || '')
    .toString()
    .toLowerCase()
    .replace(/[®™]/g, '')
    .replace(/[^a-z0-9؀-ۿ]+/g, ' ')
    .trim();
}

/** Reads every "<NAME>\nSAR <price>" pair currently rendered on the menu page. */
async function extractVisiblePrices(page) {
  return page.evaluate(() => {
    const text = document.body.innerText || '';
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
    const out = [];
    for (let i = 0; i < lines.length - 1; i++) {
      const priceMatch = lines[i + 1].match(/^SAR\s*([\d,]+(?:\.\d{1,2})?)$/i);
      if (priceMatch && lines[i].length > 1 && lines[i].length < 80) {
        out.push({ name: lines[i], price: parseFloat(priceMatch[1].replace(/,/g, '')) });
      }
    }
    return out;
  }).catch(() => []);
}

async function acceptCookies(page, logger) {
  await safe.safeClick(page, 'button:has-text("Accept All Cookies")', logger, { label: 'accept-cookies' }).catch(() => {});
}

async function openLocationPicker(page, logger) {
  // A brief settle pause after cookie-banner dismissal: clicking
  // immediately while that overlay's exit transition is still running was
  // observed live to occasionally make the very next safety-guard DOM
  // read fail transiently (fails closed -> blocks a genuinely safe click,
  // logged as "[SAFETY] Blocked click"). This is the guard doing exactly
  // what it should with an unstable read - the fix is giving the page a
  // moment to settle first, not loosening the guard.
  await page.waitForTimeout(1200);
  let opened = await safe.safeClick(page, 'button:has-text("Choose your location")', logger, { label: 'choose-location' }).catch((e) => {
    if (e instanceof safe.SafetyBlockedError) return false;
    return false;
  });
  if (!opened) {
    // One extra attempt after a longer settle - never a bypass of the
    // guard itself, just a second, later-timed, equally-guarded attempt.
    await page.waitForTimeout(2000);
    await safe.safeClick(page, 'button:has-text("Choose your location")', logger, { label: 'choose-location-retry' }).catch(() => {});
  }
  // The nearby-store list renders after an async geolocation-based lookup -
  // poll for at least one store card rather than a fixed short sleep
  // (observed live to sometimes take several seconds longer than a fixed
  // 1.6s wait, causing an otherwise-present branch to be missed).
  const appeared = await safe.pollUntil(
    page,
    async () => (await page.locator('[data-testid="store-card"]').count().catch(() => 0)) > 0 || null,
    { timeoutMs: 12000, intervalMs: 500 }
  );
  if (!appeared && logger) logger.warn('[PRICE-SCRAPER] No store cards appeared within 12s of opening the location picker');
  await page.waitForTimeout(500);
}

/** Confirms a "far from restaurant" / "couldn't find address" dialog if one appears - never a final-order dialog. */
async function confirmSoftDialogIfPresent(page, logger) {
  for (const text of ['Yes, Order Here', 'Yes, Deliver Here']) {
    const btn = page.locator(`button:has-text("${text}")`).first();
    if (await btn.isVisible({ timeout: 1500 }).catch(() => false)) {
      await safe.safeClick(page, btn, logger, { label: `confirm-dialog:${text}` }).catch(() => {});
      await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
      return true;
    }
  }
  return false;
}

/** Selects the configured PICKUP branch via the store-locator UI. */
async function selectPickupStore(page, logger) {
  const card = page.locator('[data-testid="store-card"]', { hasText: CONFIG.BRANCH.branchName }).first();
  const found = await card.isVisible({ timeout: 8000 }).catch(() => false);
  if (!found) {
    logger.warn(`[PRICE-SCRAPER] Configured branch "${CONFIG.BRANCH.branchName}" not visible in the Pickup nearby list within range`);
    return false;
  }
  await safe.safeClick(page, card.locator('[data-testid="store-card-button"]').first(), logger, { label: 'store-card-button' }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
  await safe.safeClick(page, '[data-testid="store-action-button-order"]', logger, { label: 'store-action-button-order' }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS * 2);
  await confirmSoftDialogIfPresent(page, logger);
  return true;
}

/** Confirms delivery to a TEST/placeholder address near the configured branch's coordinates. */
async function selectDeliveryAddress(page, logger) {
  await safe.safeClick(page, '[data-testid="service-mode-category-toggle-label-DELIVERY"]', logger, { label: 'delivery-toggle' }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS * 2);

  const addressInput = page.locator('[data-testid="delivery-address-input"]');
  if (!(await addressInput.isVisible({ timeout: 6000 }).catch(() => false))) {
    logger.warn('[PRICE-SCRAPER] Delivery address input did not appear');
    return false;
  }
  await safe.safeClick(page, addressInput, logger, { label: 'delivery-address-input' }).catch(() => {});
  await addressInput.type(CONFIG.BRANCH.branchName, { delay: 70 }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS * 3);

  const suggestion = page.locator('[data-testid="autocomplete-options-list-item"]').first();
  if (!(await suggestion.isVisible({ timeout: 6000 }).catch(() => false))) {
    logger.warn('[PRICE-SCRAPER] No address autocomplete suggestions appeared for the configured branch name');
    return false;
  }
  await safe.safeClick(page, suggestion, logger, { label: 'address-suggestion' }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS * 3);

  // Placeholder/test street details only - see README "Security & compliance".
  const streetName = page.locator('[data-testid="delivery-street-name-input"]');
  if (await streetName.isVisible({ timeout: 4000 }).catch(() => false)) {
    await safe.safeFill(streetName, 'Test Street (TEST VALUE)', 'street name', logger).catch(() => {});
    await safe.safeFill(page.locator('[data-testid="delivery-street-number-input"]'), '1', 'street number', logger).catch(() => {});
    await page.waitForTimeout(500);
    await safe.safeClick(page, '[data-testid="deliver-here"]', logger, { label: 'deliver-here' }).catch(() => {});
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS * 2);
    await confirmSoftDialogIfPresent(page, logger);

    // After confirming, the site shows an async "We are checking which
    // restaurant will service your address..." step before navigating to
    // /en/menu - live-observed to take anywhere from ~3s to 10+s, well
    // past a single fixed sleep. Poll for the actual navigation rather
    // than guessing a delay (same reasoning as openLocationPicker's
    // store-card poll above).
    const landedOnMenu = await safe.pollUntil(page, async () => (/\/en\/menu/.test(page.url()) ? true : null), {
      timeoutMs: 20000,
      intervalMs: 500,
    });
    if (!landedOnMenu && logger) {
      logger.warn('[PRICE-SCRAPER] Did not reach /en/menu within 20s of confirming the delivery address');
    }
  }
  return true;
}

/**
 * Scrapes visible prices for one channel. Returns a Map of normalized
 * product name -> {price, rawName}, or an empty Map on any failure (never
 * throws - a missing price is recorded as null downstream, never guessed).
 */
async function scrapePricesForChannel(channel, logger) {
  const prices = new Map();
  let browser;
  try {
    browser = await chromium.launch({ headless: CONFIG.HEADLESS });
    const context = await browser.newContext({
      geolocation: { latitude: CONFIG.BRANCH.latitude, longitude: CONFIG.BRANCH.longitude },
      permissions: ['geolocation'],
      viewport: { width: 1440, height: 960 },
      userAgent: CONFIG.STATIC_API_HEADERS['user-agent'],
      locale: 'en-US',
    });
    context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
    context.setDefaultNavigationTimeout(CONFIG.PAGE_TIMEOUT);
    const page = await context.newPage();

    await page.goto(CONFIG.START_URL, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT });
    await page.waitForTimeout(4000);
    await acceptCookies(page, logger);
    await openLocationPicker(page, logger);

    const selected = channel === 'PICKUP' ? await selectPickupStore(page, logger) : await selectDeliveryAddress(page, logger);
    if (!selected) {
      logger.warn(`[PRICE-SCRAPER] Could not select a store for channel ${channel} - prices will be recorded as null for this run`);
      return prices;
    }

    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
    if (!/\/en\/menu/.test(page.url())) {
      logger.warn(`[PRICE-SCRAPER] Did not land on the menu page for channel ${channel} (at ${page.url()}) - prices will be recorded as null`);
      return prices;
    }

    // Scroll gradually through the whole menu so every lazily-rendered
    // category's prices actually make it into document.body.innerText.
    await safe.scrollGradually(page, 10, 350);
    const pairs = await extractVisiblePrices(page);
    for (const { name, price } of pairs) {
      const key = normalizeName(name);
      if (key) prices.set(key, { price, rawName: name });
    }
    logger.tag('PRICE-SCRAPER', `Scraped ${prices.size} name/price pair(s) for channel ${channel}`);
  } catch (e) {
    logger.warn(`[PRICE-SCRAPER] Failed for channel ${channel}: ${e.message}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
  return prices;
}

function lookupPrice(pricesMap, productName) {
  const key = normalizeName(productName);
  if (!key) return null;
  if (pricesMap.has(key)) return pricesMap.get(key).price;
  // Fallback: fuzzy substring match, since combo/section names can carry
  // slightly different punctuation between the API and the rendered page.
  for (const [k, v] of pricesMap.entries()) {
    if (k === key || k.includes(key) || key.includes(k)) return v.price;
  }
  return null;
}

module.exports = {
  scrapePricesForChannel,
  lookupPrice,
  normalizeName,
  extractVisiblePrices,
  // Exported so screenshot-capture.js can reuse the exact same,
  // already-verified navigation steps instead of duplicating them.
  acceptCookies,
  openLocationPicker,
  confirmSoftDialogIfPresent,
  selectPickupStore,
  selectDeliveryAddress,
};
