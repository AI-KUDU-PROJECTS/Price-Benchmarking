'use strict';

/**
 * collector/api-bootstrap.js
 * ---------------------------------------------------------------------
 * The ONLY module in this system that launches a real browser for API
 * collection purposes (screenshot-capture.js is separate and only runs for
 * NEW_PRODUCT events). Per the required architecture:
 *
 *   API First -> Playwright Bootstrap only when required -> ... -> direct
 *   API calls
 *
 * Herfy's storefront (order.herfy.com) runs on the third-party "Solo"
 * ordering platform. Its entire menu/category/pricing/modifier catalog is
 * server-side-rendered into the page's `window.__NUXT__` client state -
 * but that state is assigned via a minified IIFE with webpack/Nuxt-style
 * string-literal deduplication (`(function(a,b,c,...){...})(...)`), NOT
 * plain JSON, so a bare regex-extract-then-JSON.parse() on the raw HTML
 * does not work (confirmed live - see research/api-map/api-map.md "How
 * this was verified"). This module's ENTIRE job is therefore:
 *
 *   1. page.goto() the storefront root page once,
 *   2. page.evaluate(() => window.__NUXT__) to let the browser's own JS
 *      engine evaluate that expression and hand back the real object,
 *   3. read out the two non-secret, per-application (not per-session)
 *      values every subsequent call needs: `key` (the "solo-app" header)
 *      and `menu-ref` (a direct CDN URL to the full current menu JSON).
 *
 * No clicking, no form-filling, no session/cookie capture happens here -
 * unlike KFC's api-bootstrap.js (which must wait for guest-login traffic
 * and capture auth headers), Herfy's storefront needs no session at all.
 * The returned bootstrap object holds only these two public identifiers
 * in memory for the current run - never written to git, never logged in
 * full (see README "Security & compliance").
 * ---------------------------------------------------------------------
 */

const { chromium } = require('playwright');
const CONFIG = require('./config');

/**
 * Loads the storefront root page once and extracts the app-bootstrap
 * values from its embedded window.__NUXT__ state. Retries the page load
 * itself (not the whole browser launch) up to MAX_RETRIES+1 times.
 */
async function bootstrapApp(logger) {
  const browser = await chromium.launch({ headless: CONFIG.HEADLESS });
  try {
    const context = await browser.newContext({
      locale: 'en-US',
      viewport: { width: 1440, height: 960 },
      userAgent: CONFIG.STATIC_API_HEADERS['user-agent'],
    });
    context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
    const page = await context.newPage();

    let lastError = null;
    let nuxtState = null;
    for (let attempt = 0; attempt <= CONFIG.MAX_RETRIES; attempt++) {
      try {
        if (attempt > 0) {
          if (logger) logger.warn(`[BOOTSTRAP] Retrying page load (attempt ${attempt + 1}/${CONFIG.MAX_RETRIES + 1})`);
          await new Promise((r) => setTimeout(r, 3000 * attempt));
        }
        await page.goto(CONFIG.START_URL, { waitUntil: 'networkidle', timeout: CONFIG.PAGE_TIMEOUT });
        nuxtState = await page.evaluate(() => {
          try {
            return window.__NUXT__ || null;
          } catch (e) {
            return null;
          }
        });
        if (nuxtState && nuxtState.state && nuxtState.state.app && nuxtState.state.app.settings) {
          break;
        }
        lastError = new Error('window.__NUXT__.state.app.settings was not present after page load');
        nuxtState = null;
      } catch (e) {
        lastError = e;
      }
    }
    if (!nuxtState) {
      throw new Error(`Could not read app-bootstrap state after ${CONFIG.MAX_RETRIES + 1} attempt(s): ${lastError ? lastError.message : 'unknown error'}`);
    }

    const settings = nuxtState.state.app.settings && nuxtState.state.app.settings.attributes;
    const concept = nuxtState.state.concept && nuxtState.state.concept.concept && nuxtState.state.concept.concept.attributes;
    if (!settings || !settings.key) {
      throw new Error('app.settings.attributes.key (the solo-app App Key) was not present in window.__NUXT__');
    }
    if (!settings['menu-ref']) {
      throw new Error("app.settings.attributes['menu-ref'] (the CDN menu URL) was not present in window.__NUXT__");
    }

    if (logger) {
      logger.success(
        `[BOOTSTRAP] App settings read (key captured, default-menu-id=${settings['default-menu-id']}, ` +
          `menu-ref=${settings['menu-ref']})`
      );
    }

    return {
      appKey: settings.key,
      menuRef: settings['menu-ref'],
      defaultMenuId: settings['default-menu-id'],
      applicationId: nuxtState.state.app.settings.id,
      concept: concept
        ? { id: nuxtState.state.concept.concept.id, currency: concept['currency-code'], vatRate: concept['vat-rate'], vatType: concept['vat-type'] }
        : null,
    };
  } finally {
    await browser.close();
  }
}

module.exports = { bootstrapApp };
