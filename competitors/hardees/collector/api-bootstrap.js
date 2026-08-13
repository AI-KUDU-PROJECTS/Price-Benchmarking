'use strict';

/**
 * collector/api-bootstrap.js
 * ---------------------------------------------------------------------
 * The ONLY module in this system that launches a real browser for API
 * collection purposes (screenshot-capture.js is separate and only runs for
 * NEW_PRODUCT/NEW_OFFER events). Per the required architecture:
 *
 *   API First -> Playwright Bootstrap only when required -> ... -> direct
 *   API calls
 *
 * Identical to competitors/kfc/collector/api-bootstrap.js - Hardee's KSA
 * runs on the exact same Americana-operated platform (confirmed live, see
 * research/api-map/api-map.md), so this module's job is identical: load
 * the real site once, capture the guest session (cookies + non-secret/
 * secret headers) and the blob-storage SAS token (needed as a payload
 * field on getStoreList/getMenu/getProductsByCategory), then hand that
 * "session" object back so every subsequent call can be made as a direct
 * HTTPS request via api-client.js - no further browser involvement.
 *
 * The one addition versus KFC's version: `ignoreHTTPSErrors: true` on the
 * browser context, because saudi.hardees.me's own TLS certificate was
 * found EXPIRED at verification time - see config.js's module docstring
 * "Known quirk".
 *
 * The session object holds only what the CURRENT run needs in memory. It
 * is never written to git and is deleted from disk (see collect.js) at the
 * end of every run - see README "Security & compliance" and api-map.md
 * "What is never recorded".
 * ---------------------------------------------------------------------
 */

const { chromium } = require('playwright');
const CONFIG = require('./config');

const SENSITIVE_HEADER_NAMES = new Set(['cookie', 'authorization', 'refreshtoken']);
const HEADER_NAMES_TO_CAPTURE = [
  'deviceid', 'brand', 'country', 'language', 'version', 'devicemodel',
  'is-dark-mode', 'authorization', 'refreshtoken', 'channel', 'brandname',
];

/**
 * Loads the real site once, waits for the guest-session bootstrap traffic
 * to fire, and returns a session object usable by api-client.js.
 * Retries the page load itself (not the whole browser launch) up to
 * MAX_RETRIES+1 times.
 */
async function bootstrapSession(logger) {
  const browser = await chromium.launch({ headless: CONFIG.HEADLESS });
  try {
    const context = await browser.newContext({
      geolocation: { latitude: CONFIG.BRANCH.latitude, longitude: CONFIG.BRANCH.longitude },
      permissions: ['geolocation'],
      locale: 'en-US',
      viewport: { width: 1440, height: 960 },
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      ignoreHTTPSErrors: CONFIG.IGNORE_TLS_ERRORS,
    });
    context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
    const page = await context.newPage();

    const capturedHeaders = {};
    let blob = null;
    let guestLoginSeen = false;

    page.on('response', async (res) => {
      const url = res.url();
      if (!url.includes('/api/')) return;
      try {
        const req = res.request();
        const headers = req.headers();
        for (const name of HEADER_NAMES_TO_CAPTURE) {
          if (headers[name] !== undefined && headers[name] !== '') capturedHeaders[name] = headers[name];
        }
        if (url.includes('/api/guestLogin')) guestLoginSeen = true;
        if (url.includes('/api/getAppConfig')) {
          const ct = res.headers()['content-type'] || '';
          if (ct.includes('json')) {
            const body = await res.json().catch(() => null);
            const b = body && body.data && body.data.blobBaseUrl;
            if (b && b.SASToken && b.jsonBase) blob = { jsonBase: b.jsonBase, sasToken: b.SASToken };
          }
        }
      } catch (e) {
        // Never let response inspection crash the bootstrap.
      }
    });

    let lastError = null;
    let ready = false;
    const perAttemptPollMs = Math.max(15000, Math.floor(CONFIG.PAGE_TIMEOUT / 2));
    for (let attempt = 0; attempt <= CONFIG.MAX_RETRIES; attempt++) {
      try {
        if (attempt > 0) {
          if (logger) logger.warn(`[BOOTSTRAP] Retrying page load (attempt ${attempt + 1}/${CONFIG.MAX_RETRIES + 1})`);
          await new Promise((r) => setTimeout(r, 3000 * attempt));
        }
        await page.goto(CONFIG.START_URL, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT });
        const title = await page.title();
        if (/502|error|bad gateway/i.test(title)) {
          lastError = new Error(`Unexpected page title after load: "${title}"`);
          continue;
        }

        const deadline = Date.now() + perAttemptPollMs;
        while (Date.now() < deadline && (!guestLoginSeen || !blob || !capturedHeaders.deviceid)) {
          await page.waitForTimeout(500);
        }
        if (guestLoginSeen && blob && capturedHeaders.deviceid) {
          ready = true;
          break;
        }
        lastError = new Error(
          `Guest session bootstrap traffic did not complete within ${perAttemptPollMs}ms (guestLoginSeen=${guestLoginSeen}, blob=${!!blob}, deviceid=${!!capturedHeaders.deviceid})`
        );
      } catch (e) {
        lastError = e;
      }
    }
    if (!ready) {
      throw new Error(`Could not establish a guest session after ${CONFIG.MAX_RETRIES + 1} attempt(s): ${lastError ? lastError.message : 'unknown error'}`);
    }
    if (!blob) {
      throw new Error('getAppConfig did not return a usable blob SAS token within the timeout - see api-map.md getAppConfig');
    }

    const cookies = (await context.cookies()).map((c) => ({ name: c.name, value: c.value }));
    if (logger) logger.success(`[BOOTSTRAP] Session established (deviceid captured, ${cookies.length} cookie(s), blob token captured)`);

    const headers = {};
    for (const name of HEADER_NAMES_TO_CAPTURE) {
      if (SENSITIVE_HEADER_NAMES.has(name)) continue;
      if (capturedHeaders[name] !== undefined) headers[name] = capturedHeaders[name];
    }
    // authorization/refreshtoken are session-sensitive but are still needed
    // in-memory to make authenticated-as-guest calls; they are kept only on
    // the returned object (never logged, never serialized to api-map.*).
    if (capturedHeaders.authorization) headers.authorization = capturedHeaders.authorization;
    if (capturedHeaders.refreshtoken !== undefined) headers.refreshtoken = capturedHeaders.refreshtoken;

    return { cookies, headers, blob };
  } finally {
    await browser.close();
  }
}

module.exports = { bootstrapSession };
