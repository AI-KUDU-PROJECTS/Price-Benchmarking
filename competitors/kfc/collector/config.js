'use strict';

/**
 * collector/config.js
 * ---------------------------------------------------------------------
 * Central configuration for the KFC Saudi price/offer monitor's Node.js
 * collection layer (API bootstrap, direct API calls, Playwright
 * screenshots). Everything is driven by environment variables (see
 * .env.example) so the collector can be re-run against a different branch
 * or with different limits without touching code. Every other collector/*
 * module requires() this file rather than reading process.env directly.
 *
 * This is a direct descendant of the project's original config.js. The
 * safety-guard constants (FINAL_ACTION_PATTERNS, SENSITIVE_FIELD_PATTERNS,
 * robots.txt handling) are preserved verbatim because screenshot-capture.js
 * still drives a real browser page and must never be able to place an
 * order, submit a form, or leak session data - same guarantee as before,
 * just scoped to a much smaller surface (open a product/offer page, take a
 * screenshot, leave).
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
  BASE_URL: process.env.KFC_BASE_URL || 'https://saudi.kfc.me',
  START_URL: process.env.START_URL || 'https://saudi.kfc.me/en/home',
  HEADLESS: toBool(process.env.HEADLESS, true),

  // --- Fixed branch (defaults per spec; override in .env) -------------------
  // EUROMARCHE/143 - switched from RABWAH/223 when that branch was closed for
  // Pickup (getNewStore returned storeId=0). EUROMARCHE was among the 2026-08-06
  // candidates confirmed for both Pickup and Delivery. See api-map.md.
  BRANCH: {
    city: process.env.KFC_CITY || 'Riyadh',
    branchName: process.env.KFC_BRANCH_NAME || 'EUROMARCHE',
    storeId: toInt(process.env.KFC_STORE_ID, 143),
    latitude: toFloat(process.env.KFC_LATITUDE, 24.70453454),
    longitude: toFloat(process.env.KFC_LONGITUDE, 46.66464865),
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
  // See README "Compliance & safety". saudi.kfc.me/robots.txt disallows
  // crawling of cart / checkout / registration / notification / banners
  // paths. This system never needs any of those (menu/offer pages only),
  // but the guard stays in place as defense-in-depth exactly like before.
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
    'saudi.kfc.me',
    'kfc.me',
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
  // Static, non-sensitive header values observed on saudi.kfc.me's own
  // first-party API calls. The per-run SESSION values (deviceid, cookies,
  // authorization/refreshtoken tokens) are NEVER hardcoded here - they are
  // captured live from the Playwright bootstrap (collector/api-bootstrap.js)
  // for THIS run only, held in memory / a gitignored temp file, and are
  // never committed, logged, or written into api-map.json/api-map.md.
  STATIC_API_HEADERS: {
    accept: 'application/json, text/plain, */*',
    'content-type': 'application/json',
    brand: 'KFC',
    country: 'KSA',
    language: 'En',
    version: 'v20',
    devicemodel: 'Chrome',
    'is-dark-mode': '0',
    'accept-language': 'en-US',
    // The site's edge WAF (Azure Application Gateway) 403s any request
    // missing a browser-shaped User-Agent/Origin/Referer, even with a
    // otherwise-valid session - confirmed live on 2026-08-05. These three
    // are not secret (every browser sends them plainly) but ARE required
    // for direct API calls to be accepted after the Playwright bootstrap.
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    origin: 'https://saudi.kfc.me',
    referer: 'https://saudi.kfc.me/en/home',
  },
};

module.exports = CONFIG;
