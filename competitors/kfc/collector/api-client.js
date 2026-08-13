'use strict';

/**
 * collector/api-client.js
 * ---------------------------------------------------------------------
 * Typed wrappers around every endpoint documented in ../api-map.json /
 * ../api-map.md, built on top of http-client.js. Every call:
 *   1. Builds the request from a `session` object (cookies + non-sensitive
 *      + sensitive headers captured once by api-bootstrap.js),
 *   2. Sends it via a direct HTTPS request (no browser involved - this is
 *      the "continue using direct API calls" half of the architecture),
 *   3. Validates the response against the minimal expected shape,
 *   4. Returns a uniform { ok, status, data, raw, error, schemaError }
 *      result - it NEVER throws for a bad HTTP status or a schema
 *      mismatch, because a single failed category must not crash an
 *      entire channel run (see README "Schema validation").
 * ---------------------------------------------------------------------
 */

const CONFIG = require('./config');
const http = require('./http-client');

const BASE_URL = CONFIG.BASE_URL;

function buildHeaders(session, extra = {}) {
  return {
    ...CONFIG.STATIC_API_HEADERS,
    ...(session.headers || {}),
    cookie: http.serializeCookies(session.cookies || []),
    ...extra,
  };
}

/** Merges any Set-Cookie headers from a response back into the session's cookie jar, keyed by cookie name. */
function mergeSetCookies(session, responseHeaders) {
  const setCookie = responseHeaders && responseHeaders['set-cookie'];
  if (!setCookie || !setCookie.length) return;
  const jar = new Map((session.cookies || []).map((c) => [c.name, c.value]));
  for (const line of setCookie) {
    const [pair] = line.split(';');
    const eq = pair.indexOf('=');
    if (eq === -1) continue;
    const name = pair.slice(0, eq).trim();
    const value = pair.slice(eq + 1).trim();
    if (name) jar.set(name, value);
  }
  session.cookies = Array.from(jar.entries()).map(([name, value]) => ({ name, value }));
}

async function call(session, { method, path, payload, logger, label }) {
  const url = `${BASE_URL}${path}`;
  const headers = buildHeaders(session);
  try {
    const res = await http.request({ method, url, headers, body: payload, timeoutMs: CONFIG.API_TIMEOUT });
    mergeSetCookies(session, res.headers);
    if (res.parseError) {
      if (logger) logger.warn(`[API] ${label || path}: response was not valid JSON (${res.parseError})`);
      return { ok: false, status: res.status, data: null, raw: res.body, error: `Invalid JSON: ${res.parseError}` };
    }
    const body = res.json;
    const httpOk = res.status >= 200 && res.status < 300;
    return { ok: httpOk, status: res.status, data: body, raw: res.body, error: httpOk ? null : (body && body.message) || `HTTP ${res.status}` };
  } catch (e) {
    if (logger) logger.error(`[API] ${label || path} request failed: ${e.message}`);
    return { ok: false, status: null, data: null, raw: null, error: e.message };
  }
}

/** Reads `obj[path]` by dot-notation; returns undefined if any segment is missing. */
function getPath(obj, dotPath) {
  const parts = dotPath.split('.');
  let cur = obj;
  for (const p of parts) {
    if (cur === null || cur === undefined || typeof cur !== 'object') return undefined;
    cur = cur[p];
  }
  return cur;
}

/** True if `obj[path]` (dot-notation) exists and, if `mustBeArray`, is an array. */
function has(obj, dotPath, mustBeArray = false) {
  const cur = getPath(obj, dotPath);
  if (cur === undefined || cur === null) return false;
  if (mustBeArray) return Array.isArray(cur);
  return true;
}

function schemaCheck(result, requiredPaths, arrayPaths = []) {
  if (!result.ok) return { valid: false, reason: result.error || 'non-2xx status' };
  for (const p of requiredPaths) {
    if (!has(result.data, p)) return { valid: false, reason: `missing expected field: ${p}` };
  }
  for (const p of arrayPaths) {
    if (!has(result.data, p, true)) return { valid: false, reason: `expected array field is not an array: ${p}` };
  }
  return { valid: true, reason: null };
}

// --- Endpoint wrappers, one per api-map.json entry ------------------------

async function getStoreList(session, logger) {
  const payload = { payload: { path: session.blob.jsonBase, country: 'ksa', subPath: session.blob.sasToken } };
  const result = await call(session, { method: 'POST', path: '/api/getStoreList', payload, logger, label: 'getStoreList' });
  const schema = schemaCheck(result, ['data'], ['data']);
  return { ...result, schema };
}

async function validateLocation(session, { lat, lng }, logger) {
  const payload = { lat, lng, screen: 'LOCATION', addressSubType: 'DELIVERY' };
  const result = await call(session, { method: 'POST', path: '/api/validateLocation', payload, logger, label: 'validateLocation' });
  // A 400/409 "not deliverable" response is a VALID, well-formed answer (not a schema error) - only
  // flag as a schema problem if we got a 200 without the expected store data.
  if (result.status === 400 || result.status === 409) {
    return { ...result, schema: { valid: true, reason: null }, deliverable: false };
  }
  const schema = schemaCheck(result, ['data']);
  return { ...result, schema, deliverable: result.ok && schema.valid };
}

async function getNewStore(session, { lat, lng }, logger) {
  const payload = { lat, lng };
  const result = await call(session, { method: 'POST', path: '/api/getNewStore', payload, logger, label: 'getNewStore' });
  const schema = schemaCheck(result, ['data.storeId']);
  return { ...result, schema };
}

async function getMenuConfig(session, { orderType, storeId }, logger) {
  const payload = { orderType, ...(storeId != null ? { storeId } : {}) };
  const result = await call(session, { method: 'POST', path: '/api/getMenuConfig', payload, logger, label: 'getMenuConfig' });
  const schema = schemaCheck(result, ['data.menuConfigId', 'data.clusterId']);
  return { ...result, schema };
}

async function getMenu(session, { menuConfigId, menuTempId, service }, logger) {
  const payload = {
    payload: {
      path: '',
      brand: 'kfc',
      country: 'ksa',
      defMenu: 1,
      menu: menuTempId,
      locale: 'En',
      service,
      menuConfigId,
      subPath: session.blob.sasToken,
    },
  };
  const result = await call(session, { method: 'POST', path: '/api/getMenu', payload, logger, label: 'getMenu' });
  const schema = schemaCheck(result, ['data.categories'], ['data.categories']);
  return { ...result, schema };
}

async function getProductsByCategory(session, { categoryId, cluster, configId, service, menuTempId }, logger) {
  const payload = {
    id: categoryId,
    cluster,
    configId,
    path: '',
    brand: 'kfc',
    country: 'ksa',
    locale: 'En',
    service,
    menu: menuTempId,
    subPath: session.blob.sasToken,
  };
  const result = await call(session, { method: 'POST', path: '/api/getProductsByCategory', payload, logger, label: `getProductsByCategory(${categoryId})` });
  // Live-confirmed 2026-08-05: the response's `data` IS the category object
  // itself (id, name, services, ...) with `products` as an inline array on
  // it - NOT a further-nested {data: {products}} wrapper as the minified
  // bundle's optional-chaining suggested. See api-map.md for the full note.
  const schema = schemaCheck(result, ['data.products'], ['data.products']);
  return { ...result, schema };
}

async function getHome(session, { menuConfigId, cluster, menuTempId }, logger) {
  const payload = {
    path: '',
    country: 'ksa',
    defMenu: 1,
    defTemp: menuTempId,
    cluster,
    locale: 'En',
    subPath: session.blob.sasToken,
    menuConfigId,
  };
  const result = await call(session, { method: 'POST', path: '/api/getHome', payload, logger, label: 'getHome' });
  // Supplementary call (see api-map.md) - only used to learn the numeric
  // menuId that getProgressivePromotion wants. A missing/invalid response
  // here never fails a run; callers treat this as best-effort.
  const schema = schemaCheck(result, ['data.menuId']);
  return { ...result, schema };
}

async function getProgressivePromotion(session, { orderType, menuId, menuTempId, cluster, configId }, logger) {
  const payload = { orderType, menuId, menuTempId, curMenuId: menuId, curMenuTemplateId: menuTempId, cluster, configId };
  const result = await call(session, { method: 'POST', path: '/api/getProgressivePromotion', payload, logger, label: 'getProgressivePromotion' });
  // Response shape here is the least certain (see api-map.md). Any 2xx with
  // a `data` key (array or object; an empty array means "no active
  // progressive promotion", which is a perfectly valid answer) is accepted.
  const schema = schemaCheck(result, ['data']);
  return { ...result, schema };
}

module.exports = {
  buildHeaders,
  mergeSetCookies,
  call,
  schemaCheck,
  getPath,
  getStoreList,
  validateLocation,
  getNewStore,
  getMenuConfig,
  getMenu,
  getHome,
  getProductsByCategory,
  getProgressivePromotion,
};
