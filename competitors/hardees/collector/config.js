'use strict';

/**
 * collector/config.js
 * ---------------------------------------------------------------------
 * Central configuration for the Hardee's Saudi price/offer monitor's
 * Node.js collection layer (API bootstrap, direct API calls, Playwright
 * screenshots). Hardee's KSA (saudi.hardees.me) runs on the EXACT SAME
 * Americana-operated digital ordering platform as KFC Saudi
 * (saudi.kfc.me) - confirmed live (see research/api-map/api-map.md "How
 * this was verified"): identical endpoint names (guestLogin,
 * getAppConfig, getStoreList, getNewStore, validateLocation,
 * getMenuConfig, getMenu, getProductsByCategory, getHome,
 * getProgressivePromotion), identical Azure Blob Storage SAS-token
 * payload pattern, identical robots.txt structure, and even a shared
 * "kfcloyalty" API namespace reused verbatim for Hardee's loyalty calls.
 * This file mirrors competitors/kfc/collector/config.js's shape exactly;
 * the safety-guard constants (FINAL_ACTION_PATTERNS,
 * SENSITIVE_FIELD_PATTERNS, robots.txt handling) are preserved verbatim
 * for the same reason (screenshot-capture.js still drives a real browser
 * page and must never place an order, submit a form, or leak session
 * data).
 *
 * KNOWN QUIRK (see api-map.md "Known limitation: expired TLS
 * certificate"): saudi.hardees.me's own TLS certificate was found EXPIRED
 * at verification time (2026-08-11, expired 2026-07-20) - a real
 * operational issue on the target site's own infrastructure, not
 * anything on this collector's end. Every module that connects to it
 * (api-bootstrap.js's Playwright context, and http-client.js's direct
 * HTTPS calls) is configured to tolerate this - see IGNORE_TLS_ERRORS
 * below - since this brand's real prices/offers are otherwise not
 * reachable at all. This is flagged loudly rather than silently patched
 * over; revisit if the certificate is ever renewed.
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
  BASE_URL: process.env.HRD_BASE_URL || 'https://saudi.hardees.me',
  START_URL: process.env.HRD_START_URL || 'https://saudi.hardees.me/en/home',
  HEADLESS: toBool(process.env.HEADLESS, true),
  // See module docstring "Known quirk" - saudi.hardees.me's own TLS cert
  // was found expired at verification time. Never disabled silently -
  // every place this is read logs/documents why.
  IGNORE_TLS_ERRORS: toBool(process.env.HRD_IGNORE_TLS_ERRORS, true),

  // --- Fixed branch (default per research; override in .env) ---------------
  // See research/api-map/api-map.md "Branch selection" for how this was
  // chosen and verified live.
  // EUROMARCHE-H / storeId 24 - confirmed live via getStoreList (cmsStatus=1,
  // services.del=1, services.tak=1) AND both getNewStore (PICKUP) and
  // validateLocation (DELIVERY) resolving back to storeId=24 for these
  // exact coordinates - the same physical retail location KFC's own
  // EUROMARCHE/143 branch uses (see api-map.md "Branch selection").
  BRANCH: {
    city: process.env.HRD_CITY || 'Riyadh',
    branchName: process.env.HRD_BRANCH_NAME || 'EUROMARCHE-H',
    storeId: toInt(process.env.HRD_STORE_ID, 24),
    latitude: toFloat(process.env.HRD_LATITUDE, 24.70452479),
    longitude: toFloat(process.env.HRD_LONGITUDE, 46.66425169),
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

  // --- robots.txt handling (screenshot capture navigates real pages) -------
  // saudi.hardees.me/robots.txt is structurally identical to KFC's own
  // (same Disallow patterns: cart/checkout/registration/notification/
  // banners) - confirmed live, see api-map.md.
  RESPECT_ROBOTS_TXT: toBool(process.env.RESPECT_ROBOTS_TXT, true),
  ROBOTS_FETCH_TIMEOUT: 8000,
  FALLBACK_ROBOTS_DISALLOW: [
    '*TEST*', '*?page*', '*test*', '*cart*', '*Cart*', '*forgotpassword*',
    '*notification*', '*SinglePageCheckout*', '/*test', '/*--', '/*?lng=ar',
    '/*?lang=en', '/*?lang=un', '/*?lng=en', '/*404/', '/*banners',
    '*?CombiType', '/Registration', '*?vpid', '*/NA/', '*ReturnUrl',
    '/registration', '*?returnurl', '*?combitype', '*?bpid', '/Scripts',
    '/Themes', '/Images', '/Halper', '/Handlers',
  ],

  ALLOWED_DOMAINS: [
    'saudi.hardees.me',
    'hardees.me',
    ...(process.env.EXTRA_ALLOWED_DOMAINS
      ? process.env.EXTRA_ALLOWED_DOMAINS.split(',').map((s) => s.trim()).filter(Boolean)
      : []),
  ],

  TRACKING_PARAMS: [
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'gclid', 'fbclid', 'msclkid', 'igshid', 'mc_eid', 'ref', 'yclid', 'dclid',
  ],

  // Text patterns that mark a "point of no return". Matching is
  // case-insensitive and whitespace-normalized. Identical to KFC's list -
  // this list is the backbone of the safety guard in safe-actions.js and
  // must never be bypassed.
  FINAL_ACTION_PATTERNS: [
    /\bplace\s*order\b/i, /\bconfirm\s*order\b/i, /\bsubmit\s*order\b/i,
    /\bpay\s*now\b/i, /\bcomplete\s*payment\b/i, /\bproceed\s*to\s*payment\b/i,
    /\border\s*now\b/i, /\bconfirm\s*(and|&)\s*pay\b/i, /\bpay\s*(and|&)\s*order\b/i,
    /\bsend\s*otp\b/i, /\bresend\s*otp\b/i, /\bverify\s*otp\b/i, /\bverify\s*code\b/i,
    /\bconfirm\s*phone\b/i, /\bconfirm\s*number\b/i, /\bconfirm\s*mobile\b/i,
    /\bcreate\s*account\b/i, /\bsign\s*up\b/i, /\bregister\b/i,
    /\bcancel\s*order\b/i, /\bcomplete\s*(the\s*)?purchase\b/i, /\bbuy\s*now\b/i,
    /\bapple\s*pay\b/i, /\bgoogle\s*pay\b/i, /\bstc\s*pay\b/i, /\bmada\s*pay\b/i,
    /\bredeem\s*points?\b/i, /\bredeem\s*gift\s*card\b/i,
  ],

  // Fields we will never programmatically fill, regardless of caller.
  SENSITIVE_FIELD_PATTERNS: [
    /otp/i, /verification.?code/i, /one.?time.?code/i,
    /card.?number/i, /\bcvv\b/i, /\bcvc\b/i, /card.?expiry/i, /\bexpiry\b/i,
    /iban/i, /bank.?account/i,
    /phone/i, /mobile/i, /whatsapp/i,
  ],

  // --- HTTP headers replayed on direct API calls ----------------------------
  // Static, non-sensitive header values observed live on saudi.hardees.me's
  // own first-party API calls (brand="HRD", country="KSA" - see api-map.md).
  // The per-run SESSION values (deviceid, cookies, authorization/
  // refreshtoken tokens) are NEVER hardcoded here - they are captured live
  // from the Playwright bootstrap (collector/api-bootstrap.js) for THIS run
  // only, held in memory, and are never committed, logged, or written into
  // api-map.json/api-map.md.
  STATIC_API_HEADERS: {
    accept: 'application/json, text/plain, */*',
    'content-type': 'application/json',
    brand: 'HRD',
    country: 'KSA',
    language: 'En',
    version: 'v20',
    devicemodel: 'Chrome',
    'is-dark-mode': '0',
    'accept-language': 'en-US',
    // Same WAF requirement confirmed for KFC applies here too - a
    // browser-shaped User-Agent/Origin/Referer is required for direct API
    // calls to be accepted after the Playwright bootstrap.
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    origin: 'https://saudi.hardees.me',
    referer: 'https://saudi.hardees.me/en/home',
  },
};

module.exports = CONFIG;
