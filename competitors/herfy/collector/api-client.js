'use strict';

/**
 * collector/api-client.js
 * ---------------------------------------------------------------------
 * Typed wrappers around Herfy's real Solo-platform endpoints (see
 * research/api-map/api-map.md for the full reference and "How this was
 * verified" - every one of these was independently re-verified with a
 * plain, cookie-less curl/https.request() during development).
 *
 * Unlike Burger King's/KFC's GraphQL, these are plain REST GET calls.
 * `getMenu()` needs no header at all (a public static CDN file);
 * `getLocationsNearby()`/`getLocationById()` need the `solo-app` App Key
 * header, which callers pass in explicitly (read once per run by
 * api-bootstrap.js - see that module's docstring for why it's never
 * hardcoded here).
 *
 * Every wrapper follows the same shape as every other competitor's
 * api-client.js: async fn(...args, logger) -> { ok, status, data, raw,
 * error, schema }. Never throws on a bad response - callers
 * (channel-collector.js) decide what a FAILED schema check means for run
 * status.
 * ---------------------------------------------------------------------
 */

const http = require('./http-client');
const CONFIG = require('./config');

function getPath(obj, dotPath) {
  return dotPath.split('.').reduce((acc, key) => (acc && typeof acc === 'object' ? acc[key] : undefined), obj);
}

function has(obj, dotPath, mustBeArray) {
  const val = getPath(obj, dotPath);
  if (val === undefined || val === null) return false;
  if (mustBeArray) return Array.isArray(val);
  return true;
}

/** Validates a parsed response body against required (and optionally array) dot-paths. */
function schemaCheck(data, requiredPaths, arrayPaths = []) {
  for (const p of requiredPaths) {
    if (!has(data, p, arrayPaths.includes(p))) {
      return { valid: false, reason: `missing or wrong-shaped field: ${p}` };
    }
  }
  return { valid: true, reason: null };
}

function buildHeaders(extra = {}) {
  return { ...CONFIG.STATIC_API_HEADERS, ...extra };
}

/** Performs one GET call and returns the common {ok, status, data, raw, error} shape. */
async function get({ url, headers = {}, logger, label }) {
  try {
    const res = await http.request({ method: 'GET', url, headers: buildHeaders(headers), timeoutMs: CONFIG.API_TIMEOUT });
    if (res.parseError) {
      return { ok: false, status: res.status, data: null, raw: res.body, error: `JSON parse error: ${res.parseError}` };
    }
    const payload = res.json;
    if (res.status >= 400 && payload && payload.error) {
      if (logger) logger.tag('API', `${label || url} returned an error body: ${JSON.stringify(payload.error)}`);
    }
    return { ok: res.status >= 200 && res.status < 300, status: res.status, data: payload, raw: payload, error: res.status >= 400 ? (payload && payload.error) || res.status : null };
  } catch (e) {
    if (logger) logger.tag('API', `${label || url} request failed: ${e.message}`);
    return { ok: false, status: null, data: null, raw: null, error: e.message };
  }
}

/**
 * The full menu: categories, items (real price/list-price/original-price/
 * calories/bilingual name+description), and modifier-groups/modifiers
 * (included side-table) - a plain static CDN JSON file, no auth needed.
 * `menuRefUrl` is read fresh each run from api-bootstrap.js's app
 * settings, never hardcoded (see that module's docstring).
 */
async function getMenu({ menuRefUrl }, logger) {
  const result = await get({ url: menuRefUrl, logger, label: 'getMenu' });
  const schema = schemaCheck(result.data, ['data', 'included.modifierGroups', 'included.modifiers'], ['data', 'included.modifierGroups', 'included.modifiers']);
  return { ...result, schema };
}

/** Finds every branch near a coordinate, sorted by distance. Requires the solo-app App Key header. */
async function getLocationsNearby({ lat, long, limit = 999, appKey }, logger) {
  const url = `${CONFIG.REST.SOLO_API_BASE}/locations?_lat=${encodeURIComponent(lat)}&_long=${encodeURIComponent(long)}&limit=${encodeURIComponent(limit)}`;
  const result = await get({ url, headers: { 'solo-app': appKey }, logger, label: 'getLocationsNearby' });
  const schema = schemaCheck(result.data, ['data'], ['data']);
  return { ...result, schema };
}

/** Single-branch lookup by id - the branch-existence/hours/channel-availability check. Requires the solo-app App Key header. */
async function getLocationById({ locationId, appKey }, logger) {
  const url = `${CONFIG.REST.SOLO_API_BASE}/locations/${encodeURIComponent(locationId)}`;
  const result = await get({ url, headers: { 'solo-app': appKey }, logger, label: 'getLocationById' });
  const schema = schemaCheck(result.data, ['data']);
  return { ...result, schema };
}

module.exports = {
  buildHeaders,
  get,
  schemaCheck,
  getPath,
  getMenu,
  getLocationsNearby,
  getLocationById,
};
