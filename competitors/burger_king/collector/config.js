'use strict';

/**
 * collector/config.js
 * ---------------------------------------------------------------------
 * Central configuration for Burger King Saudi's Node.js collection layer
 * (direct API calls, a Playwright price-scraper, Playwright screenshots).
 * Mirrors competitors/kfc/collector/config.js's shape and safety-guard
 * constants verbatim (FINAL_ACTION_PATTERNS, SENSITIVE_FIELD_PATTERNS,
 * robots.txt handling) - the guarantee (never place a real order, never
 * fill a phone/OTP/card field) is identical, just scoped to this brand.
 *
 * Unlike KFC, Burger King's transactional and menu-content GraphQL APIs
 * were confirmed live (see research/api-map/api-map.md) to require NO
 * cookies/session/auth at all - every endpoint was successfully replayed
 * standalone with a plain Node https request. There is therefore no
 * api-bootstrap.js here: collect.js talks to the APIs directly from the
 * first request. Playwright is used only for collector/price-scraper.js
 * (see api-map.md "Known limitation: live prices") and
 * collector/screenshot-capture.js (NEW_PRODUCT/NEW_OFFER only).
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
  BASE_URL: process.env.BK_BASE_URL || 'https://burgerking.com.sa',
  START_URL: process.env.BK_START_URL || 'https://burgerking.com.sa/en/',
  HEADLESS: toBool(process.env.HEADLESS, true),

  // --- Fixed branch (default per research; override in .env) ---------------
  // Dabab Street / storeId 11474 - confirmed live via GetRestaurants to have
  // mobileOrderingStatus="live", hasDelivery=true, hasTakeOut=true,
  // isAvailable=true at verification time. See research/api-map/api-map.md
  // "Branch selection" for other eligible candidates found the same way.
  BRANCH: {
    city: process.env.BK_CITY || 'Riyadh',
    branchName: process.env.BK_BRANCH_NAME || 'Dabab Street',
    storeId: toInt(process.env.BK_STORE_ID, 11474),
    latitude: toFloat(process.env.BK_LATITUDE, 24.7136),
    longitude: toFloat(process.env.BK_LONGITUDE, 46.6753),
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

  // --- robots.txt handling (price-scraper/screenshot-capture navigate real pages) ---
  // See research/api-map/api-map.md "robots.txt". burgerking.com.sa's own
  // robots.txt disallows nothing (User-agent: * / Disallow: <empty>), unlike
  // KFC - this stays in place as defense-in-depth regardless, in case that
  // changes, and because the underlying safety guard (never click a final-
  // order/payment control) does not depend on robots.txt either way.
  RESPECT_ROBOTS_TXT: toBool(process.env.RESPECT_ROBOTS_TXT, true),
  ROBOTS_FETCH_TIMEOUT: 8000,
  FALLBACK_ROBOTS_DISALLOW: [],

  ALLOWED_DOMAINS: [
    'burgerking.com.sa',
    ...(process.env.EXTRA_ALLOWED_DOMAINS
      ? process.env.EXTRA_ALLOWED_DOMAINS.split(',').map((s) => s.trim()).filter(Boolean)
      : []),
  ],

  TRACKING_PARAMS: [
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'msclkid', 'igshid', 'mc_eid', 'ref', 'yclid', 'dclid',
  ],

  // Text patterns that mark a "point of no return". Matching is
  // case-insensitive and whitespace-normalized. This list is the backbone
  // of the safety guard in safe-actions.js and must never be bypassed.
  // Identical to KFC's list plus RBI/Burger-King-specific phrasing seen on
  // this brand's checkout ("Place My Order" is BK's own literal label).
  FINAL_ACTION_PATTERNS: [
    /\bplace\s*order\b/i, /\bplace\s*my\s*order\b/i, /\bconfirm\s*order\b/i, /\bsubmit\s*order\b/i,
    /\bpay\s*now\b/i, /\bcomplete\s*payment\b/i, /\bproceed\s*to\s*payment\b/i,
    /\border\s*now\b/i, /\bconfirm\s*(and|&)\s*pay\b/i, /\bpay\s*(and|&)\s*order\b/i,
    /\bsend\s*otp\b/i, /\bresend\s*otp\b/i, /\bverify\s*otp\b/i, /\bverify\s*code\b/i,
    /\bconfirm\s*phone\b/i, /\bconfirm\s*number\b/i, /\bconfirm\s*mobile\b/i,
    /\bcreate\s*account\b/i, /\bsign\s*up\b/i, /\bregister\b/i,
    /\bcancel\s*order\b/i, /\bcomplete\s*(the\s*)?purchase\b/i, /\bbuy\s*now\b/i,
    /\bapple\s*pay\b/i, /\bgoogle\s*pay\b/i, /\bstc\s*pay\b/i, /\bmada\s*pay\b/i,
    /\bredeem\s*points?\b/i, /\bredeem\s*gift\s*card\b/i, /\bredeem\s*(a\s*)?coupon\b/i,
  ],

  // Fields we will never programmatically fill, regardless of caller.
  SENSITIVE_FIELD_PATTERNS: [
    /otp/i, /verification.?code/i, /one.?time.?code/i,
    /card.?number/i, /\bcvv\b/i, /\bcvc\b/i, /card.?expiry/i, /\bexpiry\b/i,
    /iban/i, /bank.?account/i,
    /phone/i, /mobile/i, /whatsapp/i,
  ],

  // --- HTTP headers replayed on direct API calls ----------------------------
  // Static, non-sensitive header values confirmed live against Burger King
  // Saudi's own GraphQL endpoints - see research/api-map/api-map.md. Unlike
  // KFC, none of these are session/auth values: x-session-id is a random
  // UUID generated fresh per run (see api-client.js's newSessionId()), never
  // tied to a real account and never persisted to disk or git.
  STATIC_API_HEADERS: {
    accept: '*/*',
    'content-type': 'application/json',
    'x-ui-language': 'en',
    'x-ui-region': 'SA',
    'x-ui-platform': 'web',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  },

  // GraphQL endpoints (see research/api-map/api-map.md "Endpoints").
  GRAPHQL: {
    RBI_GATEWAY: 'https://euc1-prod-bk-gateway.rbictg.com/graphql', // GetRestaurants, GetRestaurant, DeliveryRestaurant
    SANITY: 'https://czqk28jt.apicdn.sanity.io/v2023-08-01/graphql/prod_bk_sa/gen3', // GetMenuSections, featureMenu
  },
};

module.exports = CONFIG;
