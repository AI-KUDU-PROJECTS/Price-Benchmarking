'use strict';

/**
 * checkout-flow.js
 * ---------------------------------------------------------------------
 * Opens checkout, prefers guest checkout, records what contact/address
 * fields are required and which payment methods are offered, and stops.
 *
 * Hard safety boundary (in addition to the global click guard in
 * safe-actions.js): this module never fills a phone/OTP/card field, even
 * with fake data, because submitting *any* value into those fields on a
 * real site can trigger a real OTP dispatch server-side. If a form gates
 * progress behind a required phone field, the crawl simply stops there
 * and records that fact - it does not attempt to work around it.
 *
 * IMPORTANT: saudi.kfc.me/robots.txt disallows crawling
 * `*SinglePageCheckout*` / `/Registration`. This flow is gated behind
 * CONFIG.RESPECT_ROBOTS_TXT (default true) via the `robots` object passed
 * in from crawl-kfc.js - see README "Compliance & robots.txt".
 * ---------------------------------------------------------------------
 */

const CONFIG = require('../collector/config');
const safe = require('../collector/safe-actions');

const AVOID_FILL_PATTERNS = [/phone/i, /mobile/i, /whatsapp/i, /\botp\b/i, /verification/i, /\bcard\b/i, /\bcvv\b/i, /\bcvc\b/i, /iban/i];
// HTML input types that are never safe to fill, regardless of what the
// field happens to be labeled - catches a real <input type="tel"> whose
// visible label/placeholder/name doesn't obviously say "phone" (e.g. a
// generic "Contact" field implemented as type="tel").
const AVOID_FIELD_TYPES = ['tel', 'password'];

function shouldAvoidField(hint, field) {
  if (field && field.type && AVOID_FIELD_TYPES.includes(String(field.type).toLowerCase())) return true;
  return AVOID_FILL_PATTERNS.some((re) => re.test(hint || '')) || safe.isSensitiveField(hint);
}

async function findCheckoutEntry(page) {
  const strategies = [
    () => page.locator('button, a', { hasText: /^checkout$/i }).first(),
    () => page.locator('button, a', { hasText: /proceed to checkout/i }).first(),
    () => page.locator('button, a', { hasText: /go to checkout/i }).first(),
  ];
  for (const build of strategies) {
    const locator = build();
    if ((await locator.count().catch(() => 0)) > 0) return locator;
  }
  return null;
}

async function detectGuestOrLogin(page, logger, checkoutInfo) {
  const guestBtn = page.locator('button, a', { hasText: /guest/i }).first();
  const hasGuest = (await guestBtn.count().catch(() => 0)) > 0;
  checkoutInfo.guestCheckoutAvailable = hasGuest;

  const loginPrompt = page.locator('text=/log ?in to continue|please log ?in|sign in to continue/i').first();
  const loginRequired = !hasGuest && (await loginPrompt.count().catch(() => 0)) > 0;
  checkoutInfo.loginRequirement = loginRequired;

  if (hasGuest) {
    logger.tag('CHECKOUT', 'Guest checkout option found - continuing as guest (no account will be created)');
    await safe.safeClick(page, guestBtn, logger, { label: 'guest-checkout' }).catch((e) => {
      if (e instanceof safe.SafetyBlockedError) throw e;
    });
    await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
  } else if (loginRequired) {
    logger.tag('CHECKOUT', 'Checkout appears to require login - login screen is visible for observation only, no credentials will be submitted');
  } else {
    logger.tag('CHECKOUT', 'No explicit guest/login prompt detected at this step');
  }
}

/** Reads visible form fields (name/label/type/required) without filling anything. */
async function recordRequiredFields(page) {
  return page
    .evaluate(() => {
      const fields = Array.from(document.querySelectorAll('input, textarea, select'));
      return fields
        .map((f) => ({
          name: f.getAttribute('name') || f.id || null,
          label: (f.getAttribute('placeholder') || f.getAttribute('aria-label') || '').trim() || null,
          type: f.getAttribute('type') || f.tagName.toLowerCase(),
          required: !!(f.required || f.getAttribute('aria-required') === 'true'),
        }))
        .filter((f) => f.label || f.name);
    })
    .catch(() => []);
}

async function fillSafeContactFields(page, logger, checkoutInfo) {
  const fields = await recordRequiredFields(page);
  checkoutInfo.requiredContactFields = fields.filter((f) => /name|email|phone|mobile/i.test(f.label || f.name || ''));

  for (const field of checkoutInfo.requiredContactFields) {
    const hint = field.label || field.name || '';
    if (shouldAvoidField(hint, field)) {
      logger.tag('CHECKOUT', `Skipping contact field "${hint}" (type=${field.type}, phone/OTP/sensitive) - will not fill or submit it`);
      continue;
    }
    try {
      if (/name/i.test(hint) && field.name) {
        const loc = page.locator(`input[name="${field.name}"]`).first();
        if (await loc.count().catch(() => 0)) await safe.safeFill(loc, 'Test Crawler', hint, logger);
      } else if (/email/i.test(hint)) {
        const loc = field.name ? page.locator(`input[name="${field.name}"]`).first() : page.locator('input[type="email"]').first();
        if (await loc.count().catch(() => 0)) await safe.safeFill(loc, 'test-crawler@example.com', hint, logger);
      }
    } catch (e) {
      logger.warn(`[CHECKOUT] Could not fill contact field "${hint}": ${e.message}`);
    }
  }
}

async function recordPaymentMethods(page, logger, checkoutInfo) {
  const methods = await page
    .evaluate(() => {
      const nodes = Array.from(
        document.querySelectorAll('[class*="payment" i] [class*="option" i], [class*="payment" i] label, [class*="paymentMethod" i], [class*="PaymentMethod" i]')
      );
      const seen = new Set();
      const out = [];
      nodes.forEach((n) => {
        const t = (n.innerText || '').replace(/\s+/g, ' ').trim();
        if (t && t.length < 60 && !seen.has(t)) {
          seen.add(t);
          out.push(t);
        }
      });
      return out;
    })
    .catch(() => []);
  checkoutInfo.availablePaymentMethods = methods;
  if (methods.length) logger.success(`[CHECKOUT] Payment methods discovered: ${methods.join(', ')}`);
  else logger.tag('CHECKOUT', 'No payment method list detected on this screen');
}

async function runCheckoutFlow(page, context, logger, dataStore, robots) {
  logger.section('CHECKOUT FLOW');
  const checkoutInfo = {
    skipped: false,
    guestCheckoutAvailable: null,
    loginRequirement: null,
    availablePaymentMethods: [],
    requiredContactFields: [],
    requiredAddressFields: [],
    finalOrderButtonSelector: null,
    checkoutApiEndpoints: dataStore._checkoutApiUrls || [],
    stoppedAt: null,
  };
  dataStore.checkoutInformation = checkoutInfo;

  if (robots && robots.respect && robots.blocksCheckout) {
    logger.warn('[SAFETY] Skipping checkout flow: robots.txt disallows crawling checkout-related paths on this site (set RESPECT_ROBOTS_TXT=false to override, at your own compliance risk)');
    checkoutInfo.skipped = true;
    checkoutInfo.reason = 'robots.txt disallows crawling checkout-related paths (e.g. *SinglePageCheckout*); RESPECT_ROBOTS_TXT=true (default) honors that';
    checkoutInfo.stoppedAt = 'not-entered (robots.txt)';
    return checkoutInfo;
  }

  const entry = await findCheckoutEntry(page);
  if (!entry) {
    logger.warn('[CHECKOUT] No checkout entry point found (cart may be empty, or checkout only appears from a populated cart)');
    checkoutInfo.stoppedAt = 'checkout-entry-not-found';
    return checkoutInfo;
  }

  try {
    await safe.safeClick(page, entry, logger, { label: 'open-checkout' });
  } catch (e) {
    if (e instanceof safe.SafetyBlockedError) throw e;
    logger.warn(`[CHECKOUT] Could not open checkout: ${e.message}`);
    checkoutInfo.stoppedAt = 'checkout-open-failed';
    return checkoutInfo;
  }
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);

  // Log (never click) anything that looks like a final-order control, as a visible safety trace.
  await safe.scanForDangerousButtons(page, logger);

  await detectGuestOrLogin(page, logger, checkoutInfo);
  await fillSafeContactFields(page, logger, checkoutInfo);

  checkoutInfo.requiredAddressFields = (await recordRequiredFields(page)).filter((f) =>
    /address|building|street|city|district|area|postal|flat/i.test(f.label || f.name || '')
  );

  // Try to advance to an order-summary / payment-method screen via a non-dangerous "Next"/"Continue" control.
  // "Continue"/"Next" are not in FINAL_ACTION_PATTERNS, but text-matching a
  // label alone can't prove a generic-looking button isn't secretly the
  // real submit action on some step. Two extra guards around the single
  // text-match check in safe-actions.js:
  //  1. Pre-click: if a final-action-looking control is ALSO present on
  //     this same screen, don't click Continue either - that signal means
  //     we may already be on the last step, and clicking anything here is
  //     unwise. Stop instead.
  //  2. Post-click: scan the resulting page for order-confirmation-style
  //     text and loudly flag it in the output if seen, since a text-match
  //     guard can never be a 100% guarantee against every possible label.
  const nextBtn = page.locator('button', { hasText: /^(next|continue)$/i }).first();
  if (await nextBtn.count().catch(() => 0)) {
    const dangerousBeforeContinue = await safe.scanForDangerousButtons(page, logger);
    if (dangerousBeforeContinue.length) {
      logger.warn('[SAFETY] Not clicking Continue/Next: a final-action control is also present on this screen - stopping here instead.');
      checkoutInfo.finalOrderButtonSelector = `text-matched final-action control(s) present alongside Continue: ${dangerousBeforeContinue.join(' | ')}`;
    } else {
      try {
        await safe.safeClick(page, nextBtn, logger, { label: 'checkout-continue' });
        await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
      } catch (e) {
        if (e instanceof safe.SafetyBlockedError) throw e;
        logger.tag('CHECKOUT', `Could not advance past the current checkout step: ${e.message}`);
      }

      const confirmationSignal = await page
        .evaluate(() => {
          const text = (document.body.innerText || '').toLowerCase();
          const patterns = [/order\s*(confirmed|placed|received|number|#\d)/i, /thank you for your order/i, /your order has been/i, /payment\s*(successful|received|confirmed)/i];
          const hit = patterns.find((re) => re.test(text));
          return hit ? text.slice(0, 400) : null;
        })
        .catch(() => null);
      if (confirmationSignal) {
        logger.error('[SAFETY] Order-confirmation-style text detected after a "Continue" click - this needs manual review, a real order may have been affected. Stopping.');
        checkoutInfo.possibleOrderPlacedWarning = true;
        checkoutInfo.possibleOrderPlacedContext = confirmationSignal;
        checkoutInfo.stoppedAt = 'ABORTED: possible-order-confirmation text detected - see possibleOrderPlacedWarning';
        checkoutInfo.checkoutApiEndpoints = dataStore._checkoutApiUrls || [];
        return checkoutInfo;
      }
    }
  }

  await recordPaymentMethods(page, logger, checkoutInfo);
  const dangerousAtEnd = await safe.scanForDangerousButtons(page, logger);
  if (dangerousAtEnd.length) checkoutInfo.finalOrderButtonSelector = `text-matched final-action control(s): ${dangerousAtEnd.join(' | ')}`;

  logger.success('[SAFETY] Stopped before final order submission');
  checkoutInfo.stoppedAt = 'payment-method screen (or last reachable step) - final order/payment controls were detected but never clicked';
  checkoutInfo.checkoutApiEndpoints = dataStore._checkoutApiUrls || [];
  return checkoutInfo;
}

module.exports = { runCheckoutFlow, findCheckoutEntry, recordPaymentMethods, recordRequiredFields, detectGuestOrLogin };
