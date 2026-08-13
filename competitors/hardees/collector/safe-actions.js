'use strict';

/**
 * safe-actions.js
 * ---------------------------------------------------------------------
 * THE SAFETY CORE of this crawler. Every click/fill used anywhere else in
 * the project MUST go through safeClick / safeClickByText / safeFill from
 * this module rather than calling page.click()/locator.click()/fill()
 * directly. That is what makes the "never place a real order" guarantee
 * enforceable in one place instead of scattered across every flow file.
 *
 * The guard is intentionally FAIL CLOSED: if we cannot read an element's
 * text for any reason, we treat it as dangerous and refuse to click it.
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');
const CONFIG = require('./config');

class SafetyBlockedError extends Error {}

function normalizeText(t) {
  return (t || '')
    .toString()
    // Split camelCase/PascalCase boundaries ("placeOrderBtn" -> "place Order Btn")
    // and kebab-/snake_case separators ("place-order-btn" -> "place order btn")
    // into spaces BEFORE collapsing whitespace, so FINAL_ACTION_PATTERNS (which
    // use \s* between words) still matches identifiers found in data-testid/
    // class-name attributes, not just human-readable button text.
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function isDangerousText(text) {
  const norm = normalizeText(text);
  if (!norm) return false;
  return CONFIG.FINAL_ACTION_PATTERNS.some((re) => re.test(norm));
}

function isSensitiveField(hint) {
  const norm = normalizeText(hint);
  if (!norm) return false;
  return CONFIG.SENSITIVE_FIELD_PATTERNS.some((re) => re.test(norm));
}

/**
 * Inspects a Playwright Locator's visible text/attributes for danger signals.
 *
 * Everything is gathered in a SINGLE locator.evaluate() call rather than
 * several separate awaits each with their own `.catch(() => '')`. That
 * matters: an inner per-read catch would silently turn a genuine read
 * failure (element detached mid-check, navigation started, execution
 * context destroyed) into an empty string, which then reads as "safe" -
 * defeating the documented fail-closed guarantee below. With one
 * evaluate() call, any such failure propagates to the outer try/catch,
 * which is the only place that decides what "unreadable" means.
 */
async function isDangerousElement(locator) {
  try {
    const combinedText = await locator.evaluate((el) => {
      const parts = [];
      const push = (v) => { if (v) parts.push(String(v)); };
      push(el.innerText || el.textContent);
      push(el.getAttribute && el.getAttribute('aria-label'));
      push(el.getAttribute && el.getAttribute('title'));
      const labelledBy = el.getAttribute && el.getAttribute('aria-labelledby');
      if (labelledBy) {
        labelledBy.split(/\s+/).forEach((id) => {
          const ref = document.getElementById(id);
          if (ref) push(ref.innerText || ref.textContent);
        });
      }
      push(el.value);
      push(el.getAttribute && el.getAttribute('value'));
      push(el.getAttribute && el.getAttribute('data-testid'));
      return parts.join(' ');
    });
    return isDangerousText(combinedText);
  } catch (e) {
    // Fail closed: if we cannot verify an element is safe for any reason
    // (detached, mid-navigation, timed out), treat it as dangerous.
    return true;
  }
}

/** Low-level guarded click. Every other click helper funnels through this. */
async function guardedClick(locator, logger, label) {
  const dangerous = await isDangerousElement(locator);
  if (dangerous) {
    const msg = `Blocked click on potential final-action element${label ? ` (${label})` : ''}`;
    if (logger) logger.tag('SAFETY', msg);
    throw new SafetyBlockedError(msg);
  }
  await locator.click({ timeout: CONFIG.ACTION_TIMEOUT });
}

/** Click the first element matching visible text. Returns false if not found. */
async function safeClickByText(page, text, logger, options = {}) {
  if (isDangerousText(text)) {
    const msg = `Refused to even target a dangerous action by text: "${text}"`;
    if (logger) logger.tag('SAFETY', msg);
    throw new SafetyBlockedError(msg);
  }
  const locator = page.getByText(text, { exact: !!options.exact }).first();
  if ((await locator.count().catch(() => 0)) === 0) return false;
  await guardedClick(locator, logger, text);
  return true;
}

/** Click the first element matching a CSS selector or an existing Locator. */
async function safeClick(page, selectorOrLocator, logger, options = {}) {
  const locator = typeof selectorOrLocator === 'string' ? page.locator(selectorOrLocator).first() : selectorOrLocator;
  if ((await locator.count().catch(() => 0)) === 0) return false;
  await guardedClick(locator, logger, options.label || (typeof selectorOrLocator === 'string' ? selectorOrLocator : undefined));
  return true;
}

/** Click a button/link located by fuzzy visible text (case-insensitive regex-ish). */
async function safeClickByRole(page, role, name, logger) {
  if (isDangerousText(name)) {
    const msg = `Refused to even target a dangerous action by role/name: "${name}"`;
    if (logger) logger.tag('SAFETY', msg);
    throw new SafetyBlockedError(msg);
  }
  const locator = page.getByRole(role, { name, exact: false }).first();
  if ((await locator.count().catch(() => 0)) === 0) return false;
  await guardedClick(locator, logger, name);
  return true;
}

/**
 * Fill a form field, refusing outright if the field looks like it collects
 * OTP codes, card numbers, CVV, IBAN, etc. `fieldHint` should be whatever
 * label/placeholder/name text is available for the field.
 */
async function safeFill(locator, value, fieldHint, logger) {
  if (isSensitiveField(fieldHint)) {
    if (logger) logger.tag('SAFETY', `Refused to fill sensitive field: "${fieldHint}"`);
    return false;
  }
  await locator.fill(String(value), { timeout: CONFIG.ACTION_TIMEOUT });
  return true;
}

/**
 * Scan the current page for any control whose text matches a final-action
 * pattern, purely for logging/reporting - never clicks anything itself.
 */
async function scanForDangerousButtons(page, logger) {
  const patterns = CONFIG.FINAL_ACTION_PATTERNS.map((r) => ({ source: r.source, flags: r.flags }));
  const found = await page
    .evaluate((pats) => {
      const regexes = pats.map((p) => new RegExp(p.source, p.flags));
      const els = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]'));
      const hits = [];
      for (const el of els) {
        const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
        if (text && regexes.some((r) => r.test(text))) hits.push(text);
      }
      return hits;
    }, patterns)
    .catch(() => []);
  const unique = [...new Set(found)];
  if (unique.length && logger) {
    logger.tag('SAFETY', `Detected ${unique.length} final-action style control(s) on page - will not click: ${unique.join(' | ')}`);
  }
  return unique;
}

/** Best-effort dismissal of cookie banners / promo popups / overlays. */
async function dismissOverlays(page, logger) {
  const candidates = [
    'button:has-text("ACCEPT & CONTINUE")',
    'button:has-text("Accept")',
    'text=/accept all/i',
    'text=/accept cookies/i',
    'text=/i agree/i',
    'text=/allow all/i',
    '[class*="gotItButton" i]',
    'button[aria-label="Close" i]',
    '[aria-label="close" i]',
    '.modal button.close',
    '[class*="close" i][role="button"]',
    'text=/got it/i',
    'text=/no thanks/i',
    'text=/not now/i',
    'text=/maybe later/i',
  ];
  let dismissed = 0;
  for (const sel of candidates) {
    try {
      const loc = page.locator(sel).first();
      const visible = await loc.isVisible({ timeout: 700 }).catch(() => false);
      if (!visible) continue;
      if (await isDangerousElement(loc)) continue; // never touch anything danger-flagged
      await loc.click({ timeout: 1500 }).catch(() => {});
      dismissed += 1;
      if (logger) logger.tag('OVERLAY', `Dismissed overlay via selector: ${sel}`);
      await page.waitForTimeout(300);
    } catch (e) {
      // ignore and try the next candidate
    }
  }
  return dismissed;
}

async function scrollGradually(page, steps = 6, delayMs = 400) {
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, 800).catch(() => {});
    await page.waitForTimeout(delayMs);
  }
}

/**
 * Poll an async predicate every `intervalMs` until it returns a truthy
 * value or `timeoutMs` elapses. Used throughout the flow modules instead of
 * relying purely on networkidle, since this is a client-rendered SPA where
 * "idle" and "ready" are not the same thing.
 */
async function pollUntil(page, predicate, { timeoutMs = 15000, intervalMs = 500 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastResult = null;
  while (Date.now() < deadline) {
    try {
      lastResult = await predicate();
    } catch (e) {
      lastResult = null;
    }
    if (lastResult) return lastResult;
    await page.waitForTimeout(intervalMs);
  }
  return null;
}

/** Generic retry wrapper used by every flow module. */
async function retry(fn, retries, logger, label = '') {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn(attempt);
    } catch (e) {
      lastErr = e;
      if (e instanceof SafetyBlockedError) throw e; // never retry past a safety block
      if (logger) logger.tag('RETRY', `Attempt ${attempt + 1}/${retries + 1} failed for ${label}: ${e.message}`);
      await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
    }
  }
  throw lastErr;
}

async function captureFailure(page, logger, name) {
  try {
    fs.mkdirSync(CONFIG.ARTIFACTS_DIR, { recursive: true });
    const stamp = Date.now();
    const safeName = String(name).replace(/[^a-z0-9_-]+/gi, '_').slice(0, 80);
    const screenshotPath = path.join(CONFIG.ARTIFACTS_DIR, `${safeName}-${stamp}.png`);
    const htmlPath = path.join(CONFIG.ARTIFACTS_DIR, `${safeName}-${stamp}.html`);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    const html = await page.content().catch(() => '');
    fs.writeFileSync(htmlPath, html || '');
    if (logger) logger.tag('FAILURE', `Saved failure artifacts: ${screenshotPath} , ${htmlPath}`);
    return { screenshot: screenshotPath, html: htmlPath };
  } catch (e) {
    if (logger) logger.tag('FAILURE', `Could not capture failure artifacts: ${e.message}`);
    return null;
  }
}

module.exports = {
  SafetyBlockedError,
  isDangerousText,
  isSensitiveField,
  isDangerousElement,
  guardedClick,
  safeClick,
  safeClickByText,
  safeClickByRole,
  safeFill,
  scanForDangerousButtons,
  dismissOverlays,
  scrollGradually,
  pollUntil,
  retry,
  captureFailure,
};
