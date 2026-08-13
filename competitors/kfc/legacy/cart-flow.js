'use strict';

/**
 * cart-flow.js
 * ---------------------------------------------------------------------
 * Opens the cart, records its contents/totals, exercises quantity
 * increase/decrease and item removal, and probes the coupon UI (only
 * ever entering a code from TEST_COUPON - never brute forced).
 *
 * IMPORTANT: saudi.kfc.me/robots.txt disallows crawling `*cart*` /
 * `*Cart*`. This flow is gated behind CONFIG.RESPECT_ROBOTS_TXT (default
 * true) via the `robots` object passed in from crawl-kfc.js - see
 * README "Compliance & robots.txt". When gated, this module still writes
 * cart-calculations.json, just with `skipped: true` and the reason why.
 * ---------------------------------------------------------------------
 */

const CONFIG = require('../collector/config');
const safe = require('../collector/safe-actions');

async function openCart(page, logger) {
  const strategies = [
    () => page.getByRole('button', { name: /cart/i }).first(),
    () => page.locator('[aria-label*="cart" i]').first(),
    () => page.locator('[data-testid*="cart" i]').first(),
    () => page.locator('a, button', { hasText: /^cart$/i }).first(),
    () => page.locator('[class*="cartIcon" i], [class*="cart-icon" i], [class*="CartIcon" i]').first(),
  ];
  for (const build of strategies) {
    try {
      const locator = build();
      if ((await locator.count().catch(() => 0)) === 0) continue;
      await safe.safeClick(page, locator, logger, { label: 'open-cart' });
      return true;
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
      // try next strategy
    }
  }
  return false;
}

async function extractCartItems(page) {
  return page
    .evaluate(() => {
      const rows = Array.from(
        document.querySelectorAll('[class*="cartItem" i], [class*="cart-item" i], [class*="basketItem" i], [class*="CartItem" i]')
      );
      const items = [];
      const seen = new Set();
      for (const row of rows) {
        const text = (row.innerText || '').trim();
        if (!text || text.length > 400) continue;
        const nameEl = row.querySelector('[class*="name" i], h3, h4, h5');
        const qtyEl = row.querySelector('[class*="qty" i], [class*="quantity" i], input[type="number"]');
        const priceMatch = text.match(/(\d+(?:\.\d{1,2})?)/);
        const name = (nameEl ? nameEl.innerText : text.split('\n')[0] || '').trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        items.push({
          name,
          quantity: qtyEl ? (qtyEl.value || qtyEl.innerText || '').trim() || '1' : '1',
          price: priceMatch ? parseFloat(priceMatch[1]) : null,
        });
      }
      return items;
    })
    .catch(() => []);
}

async function extractCartTotals(page) {
  return page
    .evaluate(() => {
      const text = document.body.innerText || '';
      function grab(labelPattern) {
        const re = new RegExp(labelPattern + '\\s*[:\\-]?\\s*(?:SAR)?\\s*([\\d,]+(?:\\.\\d{1,2})?)', 'i');
        const m = text.match(re);
        return m ? parseFloat(m[1].replace(/,/g, '')) : null;
      }
      const minOrderMatch = text.match(/minimum\s*order[^\n]{0,80}/i);
      return {
        subtotal: grab('sub\\s*-?\\s*total'),
        discount: grab('discount'),
        vat: grab('\\bvat\\b'),
        tax: grab('\\btax(?:es)?\\b'),
        deliveryFee: grab('delivery\\s*(?:fee|charge)'),
        serviceFee: grab('service\\s*fee'),
        total: grab('\\btotal\\b'),
        minimumOrderMessage: minOrderMatch ? minOrderMatch[0].replace(/\s+/g, ' ').trim() : null,
        unavailableMessage: (text.match(/[^\n]*(currently unavailable|out of stock|no longer available)[^\n]*/i) || [null])[0],
      };
    })
    .catch(() => ({}));
}

async function updateQuantity(page, logger, direction) {
  const sel =
    direction === 'increase'
      ? '[aria-label*="increase" i], [aria-label*="plus" i], button:has-text("+")'
      : '[aria-label*="decrease" i], [aria-label*="minus" i], button:has-text("-")';
  const locator = page.locator(sel).last(); // cart-row steppers are usually last in DOM order vs. any page-level "+"
  if ((await locator.count().catch(() => 0)) === 0) return false;
  try {
    await safe.safeClick(page, locator, logger, { label: `quantity:${direction}` });
    return true;
  } catch (e) {
    if (e instanceof safe.SafetyBlockedError) throw e;
    logger.warn(`[CART] Could not ${direction} quantity: ${e.message}`);
    return false;
  }
}

async function removeItem(page, logger) {
  const strategies = [
    () => page.locator('[aria-label*="remove" i]').first(),
    () => page.locator('button', { hasText: /remove/i }).first(),
    () => page.locator('[class*="delete" i], [class*="trash" i], [class*="Delete" i]').first(),
  ];
  for (const build of strategies) {
    const locator = build();
    if ((await locator.count().catch(() => 0)) === 0) continue;
    try {
      await safe.safeClick(page, locator, logger, { label: 'remove-item' });
      return true;
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
    }
  }
  return false;
}

async function exploreCoupon(page, logger, dataStore) {
  const couponTrigger = page.locator('text=/coupon|promo\\s*code|apply\\s*code|add\\s*promo/i').first();
  if ((await couponTrigger.count().catch(() => 0)) === 0) {
    logger.tag('CART', 'No coupon/promo-code interface found in the cart');
    return;
  }
  logger.tag('CART', 'Coupon/promo interface discovered - opening it');
  await safe.safeClick(page, couponTrigger, logger, { label: 'open-coupon-ui' }).catch(() => {});
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
  dataStore.cartCalculations.couponInterfaceFound = true;

  if (!CONFIG.TEST_COUPON) {
    logger.tag('CART', 'TEST_COUPON is not set - leaving the coupon field untouched (no brute forcing of codes)');
    return;
  }
  const input = page.locator('input[placeholder*="coupon" i], input[placeholder*="promo" i]').first();
  if ((await input.count().catch(() => 0)) === 0) {
    logger.warn('[CART] Coupon input field not found even though a coupon UI trigger was located');
    return;
  }
  await safe.safeFill(input, CONFIG.TEST_COUPON, 'coupon code', logger).catch(() => {});
  const applyBtn = page.locator('button', { hasText: /^apply$/i }).first();
  if (await applyBtn.count().catch(() => 0)) {
    await safe.safeClick(page, applyBtn, logger, { label: 'apply-coupon' }).catch(() => {});
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
    logger.tag('CART', `Applied the single configured TEST_COUPON value - recording the resulting response/message only`);
  }
}

/**
 * Full cart exploration. `robots` is `{ respect, blocksCart }` computed once
 * in crawl-kfc.js from the live/fallback robots.txt rules.
 */
async function runCartFlow(page, context, logger, dataStore, robots) {
  logger.section('CART FLOW');

  if (robots && robots.respect && robots.blocksCart) {
    logger.warn('[SAFETY] Skipping cart flow: robots.txt disallows crawling cart-related paths on this site (set RESPECT_ROBOTS_TXT=false to override, at your own compliance risk)');
    dataStore.cartCalculations = {
      skipped: true,
      reason: 'robots.txt disallows crawling cart-related paths; RESPECT_ROBOTS_TXT=true (default) honors that',
      cartItems: [],
      quantities: [],
      subtotal: null,
      discounts: null,
      vat: null,
      taxes: null,
      deliveryFee: null,
      serviceFee: null,
      total: null,
      minimumOrderMessages: [],
      calculationApiEndpoint: null,
    };
    return dataStore.cartCalculations;
  }

  if (!dataStore.cartState.representativeProduct) {
    logger.tag('CART', 'No representative product was added during menu crawling - opening the cart to inspect its empty state only');
  }

  const opened = await safe.retry(() => openCart(page, logger), CONFIG.MAX_RETRIES, logger, 'open cart');
  if (!opened) {
    logger.warn('[CART] Could not find/open the cart UI');
    dataStore.cartCalculations = { skipped: false, opened: false, notes: 'cart control not found on page' };
    return dataStore.cartCalculations;
  }
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

  let items = await extractCartItems(page);
  let totals = await extractCartTotals(page);
  logger.tag('CART', `Cart opened - ${items.length} item row(s) detected, subtotal=${totals.subtotal ?? 'n/a'}`);

  if (dataStore.cartState.representativeProduct) {
    logger.tag('CART', 'Testing quantity increase');
    if (await updateQuantity(page, logger, 'increase')) {
      await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
      totals = await extractCartTotals(page);
    }
    logger.tag('CART', 'Testing quantity decrease');
    if (await updateQuantity(page, logger, 'decrease')) {
      await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
      totals = await extractCartTotals(page);
    }
  }

  await exploreCoupon(page, logger, dataStore);
  totals = await extractCartTotals(page);
  items = await extractCartItems(page);

  if (dataStore.cartState.representativeProduct) {
    logger.tag('CART', 'Removing the representative product to leave the cart empty');
    await removeItem(page, logger).catch(() => {});
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
  }

  const couponInterfaceFound = !!dataStore.cartCalculations.couponInterfaceFound;
  dataStore.cartCalculations = {
    skipped: false,
    cartItems: items,
    quantities: items.map((i) => ({ name: i.name, quantity: i.quantity })),
    subtotal: totals.subtotal,
    discounts: totals.discount,
    vat: totals.vat,
    taxes: totals.tax,
    deliveryFee: totals.deliveryFee,
    serviceFee: totals.serviceFee,
    total: totals.total,
    minimumOrderMessages: [totals.minimumOrderMessage, totals.unavailableMessage].filter(Boolean),
    couponInterfaceFound,
    calculationApiEndpoint: dataStore._lastCartApiUrl || null,
  };

  logger.success('[CART] Cart exploration complete');
  return dataStore.cartCalculations;
}

module.exports = {
  runCartFlow,
  openCart,
  extractCartItems,
  extractCartTotals,
  updateQuantity,
  removeItem,
  exploreCoupon,
};
