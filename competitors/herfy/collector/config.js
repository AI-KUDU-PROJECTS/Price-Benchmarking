'use strict';

/**
 * collector/config.js
 * ---------------------------------------------------------------------
 * Central configuration for Herfy's Node.js collection layer (a one-time
 * Playwright bootstrap + direct REST/CDN calls + Playwright screenshots).
 * Mirrors competitors/kfc's and competitors/burger_king's config.js shape
 * and safety-guard constants (FINAL_ACTION_PATTERNS,
 * SENSITIVE_FIELD_PATTERNS, robots.txt handling) - the guarantee (never
 * place a real order, never fill a phone/OTP/card field) is identical,
 * just scoped to this brand, with ARABIC patterns added throughout since
 * Herfy's storefront UI is Arabic-first (unlike KFC's/Burger King's
 * English-first UI) - see research/api-map/api-map.md.
 *
 * Herfy's storefront (order.herfy.com) runs on the third-party "Solo"
 * ordering platform (api.solo.skylinedynamics.com / cdn.getsolo.io), not
 * a Herfy-built backend. Unlike KFC, no guest-session/cookie bootstrap is
 * needed; unlike Burger King, no DOM price-scrape workaround is needed
 * either (real prices are directly in the CDN menu JSON). The ONE thing
 * still needing a (minimal, non-interactive) Playwright step is reading
 * the "solo-app" App Key + the current menu CDN URL out of the storefront
 * page's embedded window.__NUXT__ client state - see
 * collector/api-bootstrap.js and api-map.md "How this was verified".
 * ---------------------------------------------------------------------
 */

const path = require('path');

function toInt(value, fallback) {
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : fallback;
}

function toFloat(value, fallback) {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : fallback;
}

function toBool(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  const v = String(value).trim().toLowerCase();
  if (['false', '0', 'no', 'off'].includes(v)) return false;
  if (['true', '1', 'yes', 'on'].includes(v)) return true;
  return fallback;
}

const ROOT_DIR = path.join(__dirname, '..');
const DATA_DIR = path.join(ROOT_DIR, 'data');
const RAW_DIR = path.join(DATA_DIR, 'raw');
const SCREENSHOTS_DIR = path.join(DATA_DIR, 'screenshots');
const ARTIFACTS_DIR = path.join(ROOT_DIR, '.artifacts'); // scratch failure captures, gitignored

const CONFIG = {
  ROOT_DIR,
  DATA_DIR,
  RAW_DIR,
  SCREENSHOTS_DIR,
  ARTIFACTS_DIR,

  // --- Site target ---------------------------------------------------------
  BASE_URL: process.env.HERFY_BASE_URL || 'https://order.herfy.com',
  // Not a branch id - see api-map.md ("How this was verified"): '-193160'
  // happens to equal one promoted category's id. This is simply Herfy's
  // one storefront root page, used only to read the app-bootstrap state.
  START_URL: process.env.HERFY_START_URL || 'https://order.herfy.com/menu/-193160',
  HEADLESS: toBool(process.env.HEADLESS, true),

  // --- Fixed branch (default per research; override in .env) ---------------
  // RUH - Al Mogarazat - Eirad Plaza Mall 1073 / locationId 29696 - confirmed
  // live via GET /locations/29696 to have status=active, is-open=true,
  // is-open-pickup=true, is-open-deliver=true, pickup-enabled=1,
  // delivery-enabled=1 at verification time. See research/api-map/
  // api-map.md "Branch selection" for other eligible candidates.
  BRANCH: {
    city: process.env.HERFY_CITY || 'Riyadh',
    branchName: process.env.HERFY_BRANCH_NAME || 'RUH - Al Mogarazat - Eirad Plaza Mall 1073',
    locationId: toInt(process.env.HERFY_LOCATION_ID, 29696),
    latitude: toFloat(process.env.HERFY_LATITUDE, 24.76017),
    longitude: toFloat(process.env.HERFY_LONGITUDE, 46.717525),
  },
  TIMEZONE: process.env.TIMEZONE || 'Asia/Riyadh',

  // --- Collection limits / pacing (low concurrency, be gentle) --------------
  MAX_RETRIES: toInt(process.env.MAX_RETRIES, 2),
  PAGE_TIMEOUT: toInt(process.env.PAGE_TIMEOUT, 45000),
  ACTION_TIMEOUT: toInt(process.env.ACTION_TIMEOUT, 15000),
  API_TIMEOUT: toInt(process.env.API_TIMEOUT, 20000),
  DELAY_BETWEEN_REQUESTS: toInt(process.env.DELAY_BETWEEN_REQUESTS, 700),
  DELAY_BETWEEN_PAGES: toInt(process.env.DELAY_BETWEEN_PAGES, 1500),
  DELAY_BETWEEN_ACTIONS: toInt(process.env.DELAY_BETWEEN_ACTIONS, 800),
  MAX_SCREENSHOTS_PER_RUN: toInt(process.env.MAX_SCREENSHOTS_PER_RUN, 40),

  // --- robots.txt handling (api-bootstrap.js/screenshot-capture.js navigate real pages) ---
  // See research/api-map/api-map.md "robots.txt": order.herfy.com disallows
  // /checkout/, /payment/, /user/, /payment-failed - this collector never
  // requests any of those paths. Kept as defense-in-depth regardless of
  // whether that changes, same as every other competitor in this repo.
  RESPECT_ROBOTS_TXT: toBool(process.env.RESPECT_ROBOTS_TXT, true),
  ROBOTS_FETCH_TIMEOUT: 8000,
  FALLBACK_ROBOTS_DISALLOW: ['/checkout/', '/payment/', '/user/', '/payment-failed'],

  ALLOWED_DOMAINS: [
    'order.herfy.com',
    'skylinedynamics.com',
    'getsolo.io',
    ...(process.env.EXTRA_ALLOWED_DOMAINS
      ? process.env.EXTRA_ALLOWED_DOMAINS.split(',').map((s) => s.trim()).filter(Boolean)
      : []),
  ],

  TRACKING_PARAMS: [
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'msclkid', 'igshid', 'mc_eid', 'ref', 'yclid', 'dclid',
  ],

  // Text patterns that mark a "point of no return". Matching is
  // case-insensitive and whitespace-normalized (see safe-actions.js).
  // Includes the same English set as KFC/Burger King PLUS Arabic
  // equivalents, since Herfy's storefront UI is Arabic-first - a button
  // labeled "إتمام الطلب" must be caught just as reliably as "Place Order".
  // This list is the backbone of the safety guard in safe-actions.js and
  // must never be bypassed.
  FINAL_ACTION_PATTERNS: [
    // English (kept for parity / any English-locale UI state)
    /\bplace\s*order\b/i, /\bplace\s*my\s*order\b/i, /\bconfirm\s*order\b/i, /\bsubmit\s*order\b/i,
    /\bpay\s*now\b/i, /\bcomplete\s*payment\b/i, /\bproceed\s*to\s*payment\b/i,
    /\border\s*now\b/i, /\bconfirm\s*(and|&)\s*pay\b/i, /\bpay\s*(and|&)\s*order\b/i,
    /\bsend\s*otp\b/i, /\bresend\s*otp\b/i, /\bverify\s*otp\b/i, /\bverify\s*code\b/i,
    /\bconfirm\s*phone\b/i, /\bconfirm\s*number\b/i, /\bconfirm\s*mobile\b/i,
    /\bcreate\s*account\b/i, /\bsign\s*up\b/i, /\bregister\b/i,
    /\bcancel\s*order\b/i, /\bcomplete\s*(the\s*)?purchase\b/i, /\bbuy\s*now\b/i,
    /\bapple\s*pay\b/i, /\bgoogle\s*pay\b/i, /\bstc\s*pay\b/i, /\bmada\s*pay\b/i,
    /\bredeem\s*points?\b/i, /\bredeem\s*gift\s*card\b/i, /\bredeem\s*(a\s*)?coupon\b/i,
    // Arabic - Herfy's default UI language (see api-map.md "concept.primary-language")
    /اتمام\s*الطلب/, /إتمام\s*الطلب/, /تاكيد\s*الطلب/, /تأكيد\s*الطلب/, /ارسال\s*الطلب/, /إرسال\s*الطلب/,
    /ادفع\s*الان/, /ادفع\s*الآن/, /الدفع\s*الان/, /الدفع\s*الآن/, /اكمال\s*الدفع/, /إكمال\s*الدفع/,
    /ارسال\s*رمز/, /إرسال\s*رمز/, /تاكيد\s*رمز/, /تأكيد\s*رمز/, /رمز\s*التحقق/,
    /تاكيد\s*الجوال/, /تأكيد\s*الجوال/, /تاكيد\s*الهاتف/, /تأكيد\s*الهاتف/, /تاكيد\s*رقم/, /تأكيد\s*رقم/,
    /انشاء\s*حساب/, /إنشاء\s*حساب/, /تسجيل\s*جديد/, /تسجيل\s*حساب/,
    /الغاء\s*الطلب/, /إلغاء\s*الطلب/, /اتمام\s*الشراء/, /إتمام\s*الشراء/,
    /استبدال\s*نقاط/, /استخدام\s*نقاط/, /استبدال\s*قسيمة/, /استخدام\s*كوبون/,
  ],

  // Fields we will never programmatically fill, regardless of caller.
  // English + Arabic hint patterns (field labels/placeholders on this
  // storefront are primarily Arabic).
  SENSITIVE_FIELD_PATTERNS: [
    /otp/i, /verification.?code/i, /one.?time.?code/i,
    /card.?number/i, /\bcvv\b/i, /\bcvc\b/i, /card.?expiry/i, /\bexpiry\b/i,
    /iban/i, /bank.?account/i,
    /phone/i, /mobile/i, /whatsapp/i,
    /رمز.?تحقق/, /رمز.?التحقق/, /رقم.?البطاقه/, /رقم.?البطاقة/, /الجوال/, /الهاتف/, /واتساب/,
  ],

  // Non-sensitive header sent by this collector's Playwright bootstrap
  // page-load; static per-app "solo-app" value is read fresh from the
  // page each run (see api-bootstrap.js) and passed through in memory,
  // never hardcoded here and never persisted.
  STATIC_API_HEADERS: {
    accept: 'application/json',
    'accept-language': 'en-us',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  },

  // REST endpoints (see research/api-map/api-map.md "Endpoints").
  REST: {
    SOLO_API_BASE: 'https://api.solo.skylinedynamics.com', // /locations, /locations/{id}
  },
};

module.exports = CONFIG;
