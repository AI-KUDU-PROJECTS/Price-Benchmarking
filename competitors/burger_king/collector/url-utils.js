'use strict';

/**
 * collector/url-utils.js
 * URL normalization, domain allow-listing, robots.txt handling, and
 * defensive JSON-payload scanning helpers shared by every collector/*
 * module. The robots.txt + domain helpers are used by price-scraper.js and
 * screenshot-capture.js (the two modules that still drive a real browser
 * page); the JSON scanning helpers are used by the API client as a
 * fallback when a live response uses an unexpected field name for
 * something still needed. Identical to competitors/kfc's url-utils.js.
 */

const https = require('https');
const CONFIG = require('./config');

function getHostname(rawUrl) {
  try {
    return new URL(rawUrl).hostname.replace(/^www\./, '').toLowerCase();
  } catch (e) {
    return null;
  }
}

function hostMatches(host, domain) {
  return host === domain || host.endsWith('.' + domain);
}

function isAllowedDomain(rawUrl) {
  const host = getHostname(rawUrl);
  if (!host) return false;
  return CONFIG.ALLOWED_DOMAINS.some((d) => hostMatches(host, d));
}

/**
 * Normalize a URL relative to a base: strips the fragment, removes tracking
 * params, sorts the remaining query params for a stable dedupe key, and
 * trims a trailing slash (except for the root path).
 */
function normalizeUrl(rawUrl, baseUrl) {
  try {
    const u = new URL(rawUrl, baseUrl);
    u.hash = '';
    CONFIG.TRACKING_PARAMS.forEach((p) => u.searchParams.delete(p));
    const sortedParams = [...u.searchParams.entries()].sort(([a], [b]) => a.localeCompare(b));
    u.search = '';
    sortedParams.forEach(([k, v]) => u.searchParams.append(k, v));
    let href = u.toString();
    if (href.endsWith('/') && u.pathname !== '/') href = href.slice(0, -1);
    return href;
  } catch (e) {
    return null;
  }
}

function createUrlTracker() {
  const visited = new Set();
  return {
    has: (u) => visited.has(u),
    add: (u) => visited.add(u),
    size: () => visited.size,
    values: () => Array.from(visited),
  };
}

async function extractLinksFromPage(page, baseUrl) {
  const rawLinks = await page
    .evaluate(() => {
      const out = new Set();
      document.querySelectorAll('a[href]').forEach((a) => out.add(a.getAttribute('href')));
      document.querySelectorAll('link[href]').forEach((l) => out.add(l.getAttribute('href')));
      return Array.from(out);
    })
    .catch(() => []);

  const normalized = new Set();
  for (const raw of rawLinks) {
    if (!raw || /^(javascript|mailto|tel):/i.test(raw)) continue;
    const n = normalizeUrl(raw, baseUrl);
    if (n) normalized.add(n);
  }
  return Array.from(normalized);
}

// --- robots.txt --------------------------------------------------------

/**
 * Fetch robots.txt for the given origin using plain https (no browser
 * involved). Resolves to the raw text, or null if it could not be
 * fetched.
 */
function fetchRobotsTxt(origin) {
  return new Promise((resolve) => {
    let url;
    try {
      url = new URL('/robots.txt', origin);
    } catch (e) {
      resolve(null);
      return;
    }
    const req = https.get(
      url,
      { timeout: CONFIG.ROBOTS_FETCH_TIMEOUT, headers: { 'User-Agent': 'Mozilla/5.0 (compatible; bk-price-collector/1.0)' } },
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          resolve(null);
          return;
        }
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => resolve(data));
      }
    );
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.on('error', () => resolve(null));
  });
}

/** Parse "Disallow:" lines that fall under "User-agent: *" blocks. */
function parseRobotsDisallow(text) {
  if (!text) return [];
  const rules = [];
  let appliesToUs = false;
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.split('#')[0].trim();
    if (!line) continue;
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (key === 'user-agent') {
      appliesToUs = value === '*';
    } else if (key === 'disallow' && appliesToUs && value) {
      rules.push(value);
    }
  }
  return rules;
}

/** Convert a robots.txt Disallow value (with `*` wildcards) into a RegExp. */
function robotsPatternToRegex(pattern) {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(escaped);
}

function buildDisallowMatchers(rules) {
  return rules.map((pattern) => ({ pattern, regex: robotsPatternToRegex(pattern) }));
}

/**
 * Load robots.txt rules for the given origin: try a live fetch first, fall
 * back to the baked-in snapshot in config.js if the fetch fails (an empty
 * list for Burger King - see api-map.md). Always returns a matcher array.
 */
async function loadRobotsMatchers(origin, logger) {
  const liveText = await fetchRobotsTxt(origin);
  let rules = parseRobotsDisallow(liveText);
  if (rules.length) {
    if (logger) logger.tag('ROBOTS', `Fetched live robots.txt (${rules.length} disallow rules) from ${origin}`);
  } else {
    rules = CONFIG.FALLBACK_ROBOTS_DISALLOW;
    if (logger) logger.tag('ROBOTS', `No disallow rules from live fetch or fallback (${rules.length}) - ${liveText ? 'robots.txt allows everything' : 'live fetch unavailable'}`);
  }
  return buildDisallowMatchers(rules);
}

function isRobotsDisallowed(rawUrl, matchers) {
  if (!matchers || !matchers.length) return false;
  try {
    const u = new URL(rawUrl);
    const target = u.pathname + u.search;
    return matchers.some((m) => m.regex.test(target) || m.regex.test(rawUrl));
  } catch (e) {
    return false;
  }
}

/** Does any fetched Disallow rule reference this keyword (e.g. "cart")? */
function robotsBlocksKeyword(matchers, keyword) {
  if (!matchers || !matchers.length) return false;
  const kw = keyword.toLowerCase();
  return matchers.some((m) => m.pattern.toLowerCase().includes(kw));
}

// --- Generic JSON payload helpers ---------------------------------------
// Used to opportunistically enrich data with real API-sourced values when
// a response uses a field name not explicitly coded for.

/** Recursively collect {key, value} pairs whose key matches any pattern. */
function deepFindByKeyPattern(obj, patterns, results = [], seen = new WeakSet(), depth = 0) {
  if (!obj || typeof obj !== 'object' || depth > 12) return results;
  if (seen.has(obj)) return results;
  seen.add(obj);
  for (const [key, value] of Object.entries(obj)) {
    if (patterns.some((p) => p.test(key))) {
      if (value === null || (typeof value !== 'object' && typeof value !== 'function')) {
        results.push({ key, value });
      }
    }
    if (value && typeof value === 'object') deepFindByKeyPattern(value, patterns, results, seen, depth + 1);
  }
  return results;
}

function firstByKeyPattern(obj, patterns) {
  const found = deepFindByKeyPattern(obj, patterns);
  return found.length ? found[0].value : null;
}

/**
 * Recursively search a JSON payload for an object that looks like it
 * describes the named product/store (has a name-ish field whose value
 * fuzzily matches `name`), and return that object.
 */
function fuzzyFindObjectByName(obj, name, { nameKeyPattern = /^(name|locale|title|productname|itemname)$/i } = {}, seen = new WeakSet(), depth = 0) {
  if (!obj || typeof obj !== 'object' || depth > 12 || seen.has(obj)) return null;
  seen.add(obj);
  const target = normalizeForCompare(name);
  if (target) {
    for (const [key, value] of Object.entries(obj)) {
      if (nameKeyPattern.test(key) && typeof value === 'string') {
        const candidate = normalizeForCompare(value);
        if (candidate && (candidate === target || candidate.includes(target) || target.includes(candidate))) {
          return obj;
        }
      }
    }
  }
  for (const value of Object.values(obj)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        const found = fuzzyFindObjectByName(item, name, { nameKeyPattern }, seen, depth + 1);
        if (found) return found;
      }
    } else if (value && typeof value === 'object') {
      const found = fuzzyFindObjectByName(value, name, { nameKeyPattern }, seen, depth + 1);
      if (found) return found;
    }
  }
  return null;
}

function normalizeForCompare(s) {
  return (s || '').toString().toLowerCase().replace(/[^a-z0-9؀-ۿ]+/g, ' ').trim();
}

module.exports = {
  getHostname,
  isAllowedDomain,
  normalizeUrl,
  createUrlTracker,
  extractLinksFromPage,
  fetchRobotsTxt,
  parseRobotsDisallow,
  buildDisallowMatchers,
  loadRobotsMatchers,
  isRobotsDisallowed,
  robotsBlocksKeyword,
  deepFindByKeyPattern,
  firstByKeyPattern,
  fuzzyFindObjectByName,
  normalizeForCompare,
};
