'use strict';

/**
 * collector/channel-collector.js
 * ---------------------------------------------------------------------
 * Shared implementation behind pickup-collector.js and delivery-collector.js.
 * Both channels follow the exact same shape end to end:
 *
 *   resolve+verify branch for this channel
 *     -> getMenuConfig(orderType[, storeId]) => menuConfigId, clusterId
 *     -> getMenu(menuConfigId)                => category list
 *     -> loop getProductsByCategory(id, cluster, configId) per category
 *     -> getHome + getProgressivePromotion (best-effort)
 *
 * The only thing that differs between channels is how the branch is
 * resolved/verified (getNewStore for PICKUP, validateLocation for
 * DELIVERY) and the `orderType`/`service` value threaded through every
 * call - see resolveBranchForChannel().
 *
 * This module NEVER decides "PRODUCT_REMOVED" / "OFFER_ENDED" / etc. - it
 * only ever produces ONE channel's snapshot for ONE run, tagged with a
 * run-level status (SUCCESS / PARTIAL / FAILED). All comparison across
 * runs happens later, in Python (backend/change_detector.py), and only
 * ever between two snapshots that both have status SUCCESS - see README
 * "Critical rule to prevent false alerts".
 * ---------------------------------------------------------------------
 */

const CONFIG = require('./config');
const apiClient = require('./api-client');
const { wait, withRetry } = require('./http-client');

/**
 * Verifies the fixed branch (CONFIG.BRANCH) still exists (is configured in
 * the system) via getStoreList (spec: "verify branch still exists ... using
 * getStoreList or validateLocation"). Returns { ok, menuTempId, storeRecord,
 * error, currentlyClosed }. This check is shared by both channels and only
 * needs to run once per collect.js invocation.
 *
 * IMPORTANT: `store.active` / `store.sdmStatus` were live-confirmed
 * (2026-08-06) to reflect the branch's CURRENT real-time open/closed
 * status against its own daily operating hours (`startTime`/`endTime`),
 * NOT whether the branch still exists - a live test showed getMenuConfig /
 * getMenu / getProductsByCategory all continue to return full, correct
 * catalog data for a branch with active=0 while it is simply closed for
 * the night. Gating the whole run on that flag would fail every single
 * run scheduled outside this one branch's operating hours, which is not
 * what "branch unavailable" in the spec is guarding against (branch
 * removed/renumbered/delisted). `store.cmsStatus` (still published/
 * configured) plus the store record's mere PRESENCE under the configured
 * city are used as the real "exists" gate instead; active=0 is logged as
 * an informational note on the run, never as a failure reason.
 */
async function verifyBranchExists(session, logger) {
  // getStoreList is served straight from Azure Blob Storage and was
  // confirmed LIVE (2026-08-11) to intermittently 500 with a transient
  // "BlobNotFound" error that clears itself within a couple of seconds
  // (3/3 immediate retries succeeded in testing). apiClient calls never
  // throw/reject (see api-client.js's call()), so this retries on the
  // returned schema validity directly rather than via http-client's
  // exception-based withRetry().
  let res = await apiClient.getStoreList(session, logger);
  for (let attempt = 0; !res.schema.valid && attempt < CONFIG.MAX_RETRIES; attempt++) {
    if (logger) logger.tag('RETRY', `getStoreList attempt ${attempt + 1}/${CONFIG.MAX_RETRIES} failed (${res.schema.reason}) - retrying`);
    await wait(600 * (attempt + 1));
    res = await apiClient.getStoreList(session, logger);
  }
  if (!res.schema.valid) {
    return { ok: false, error: `getStoreList failed schema validation: ${res.schema.reason}`, raw: res };
  }
  const cities = res.data.data || [];
  const city = cities.find((c) => String(c.cityName || c.name_en || '').toLowerCase() === CONFIG.BRANCH.city.toLowerCase());
  if (!city) {
    return { ok: false, error: `Configured city "${CONFIG.BRANCH.city}" was not found in getStoreList's response`, raw: res };
  }
  const store = (city.store || []).find((s) => Number(s.storeId) === Number(CONFIG.BRANCH.storeId));
  if (!store) {
    return { ok: false, error: `Configured HRD_STORE_ID=${CONFIG.BRANCH.storeId} was not found under city "${CONFIG.BRANCH.city}" - the branch may have been removed or renumbered`, raw: res };
  }
  if (store.cmsStatus !== undefined && Number(store.cmsStatus) !== 1) {
    return { ok: false, error: `Configured branch (storeId=${CONFIG.BRANCH.storeId}, name=${store.name_en}) is present but no longer published (cmsStatus=${store.cmsStatus})`, raw: res };
  }
  const currentlyClosed = Number(store.active) !== 1;
  if (currentlyClosed && logger) {
    logger.warn(`[BRANCH] storeId=${CONFIG.BRANCH.storeId} (${store.name_en}) is currently closed for orders (active=${store.active}) - catalog data is still collected normally; this is a routine operating-hours state, not a failure`);
  }
  if (String(store.name_en || '').trim().toUpperCase() !== CONFIG.BRANCH.branchName.trim().toUpperCase()) {
    if (logger) {
      logger.warn(
        `[BRANCH] Configured HRD_BRANCH_NAME="${CONFIG.BRANCH.branchName}" does not match getStoreList's name for storeId=${CONFIG.BRANCH.storeId} ("${store.name_en}") - storeId is the authoritative identity, continuing, but consider updating .env`
      );
    }
  }
  return { ok: true, menuTempId: store.menuTempId, storeRecord: store, currentlyClosed };
}

/** PICKUP: resolve nearest branch via getNewStore and confirm it matches the configured branch. */
async function resolveBranchForChannel(session, channel, logger) {
  if (channel === 'PICKUP') {
    const res = await apiClient.getNewStore(session, { lat: CONFIG.BRANCH.latitude, lng: CONFIG.BRANCH.longitude }, logger);
    if (!res.schema.valid) return { ok: false, error: `getNewStore failed schema validation: ${res.schema.reason}` };
    const resolvedStoreId = Number(apiClient.getPath(res.data, 'data.storeId'));
    if (resolvedStoreId !== Number(CONFIG.BRANCH.storeId)) {
      return { ok: false, error: `getNewStore resolved storeId=${resolvedStoreId} for the configured coordinates, but HRD_STORE_ID=${CONFIG.BRANCH.storeId} - the nearest pickup branch for this location has changed` };
    }
    return { ok: true, storeId: resolvedStoreId };
  }
  if (channel === 'DELIVERY') {
    const res = await apiClient.validateLocation(session, { lat: CONFIG.BRANCH.latitude, lng: CONFIG.BRANCH.longitude }, logger);
    if (!res.schema.valid) return { ok: false, error: `validateLocation failed schema validation: ${res.schema.reason}` };
    if (!res.deliverable) {
      return { ok: false, error: `Configured branch does not currently deliver to the configured coordinates: ${res.error || 'not deliverable'}` };
    }
    const resolvedStoreId = Number(apiClient.getPath(res.data, 'data.store.storeId'));
    if (Number.isFinite(resolvedStoreId) && resolvedStoreId !== Number(CONFIG.BRANCH.storeId)) {
      return { ok: false, error: `validateLocation resolved storeId=${resolvedStoreId} for the configured coordinates, but HRD_STORE_ID=${CONFIG.BRANCH.storeId} - the delivering branch for this location has changed` };
    }
    return { ok: true, storeId: resolvedStoreId || CONFIG.BRANCH.storeId };
  }
  return { ok: false, error: `Unknown channel: ${channel}` };
}

/**
 * Collects one full channel snapshot. Returns a plain object matching the
 * shape run_service.py / database.py expect (see backend/models.py).
 * Never throws for a normal API failure - only an unexpected programming
 * error escapes, and collect.js wraps the whole thing in a try/catch that
 * turns even that into a FAILED result rather than a crash.
 */
async function collectChannel(session, channel, logger, { onRawResponse } = {}) {
  const startedAt = new Date().toISOString();
  const record = (endpoint, payload, res) => {
    if (onRawResponse) onRawResponse(channel, endpoint, payload, res);
  };

  logger.section(`${channel} COLLECTION`);
  logger.tag('RUN', `Starting ${channel}`);

  const branchVerify = await verifyBranchExists(session, logger);
  record('getStoreList', null, branchVerify.raw);
  if (!branchVerify.ok) {
    logger.error(`[BRANCH] ${branchVerify.error}`);
    return buildFailedResult(channel, startedAt, branchVerify.error, { categoryCount: 0, productCount: 0, offerCount: 0 });
  }

  const branchRes = await resolveBranchForChannel(session, channel, logger);
  if (!branchRes.ok) {
    logger.error(`[BRANCH] ${branchRes.error}`);
    return buildFailedResult(channel, startedAt, branchRes.error, { categoryCount: 0, productCount: 0, offerCount: 0 });
  }
  logger.success(`[BRANCH] Confirmed storeId=${CONFIG.BRANCH.storeId} (${CONFIG.BRANCH.branchName}) is available for ${channel}`);

  const menuConfigRes = await apiClient.getMenuConfig(session, { orderType: channel, storeId: channel === 'PICKUP' ? CONFIG.BRANCH.storeId : undefined }, logger);
  record('getMenuConfig', { orderType: channel }, menuConfigRes);
  if (!menuConfigRes.schema.valid) {
    const msg = `getMenuConfig failed schema validation: ${menuConfigRes.schema.reason}`;
    logger.error(`[CONFIG] ${msg}`);
    return buildFailedResult(channel, startedAt, msg, { categoryCount: 0, productCount: 0, offerCount: 0 });
  }
  const menuConfigId = apiClient.getPath(menuConfigRes.data, 'data.menuConfigId');
  const clusterId = apiClient.getPath(menuConfigRes.data, 'data.clusterId');
  logger.tag('CONFIG', `${channel} config loaded (menuConfigId=${menuConfigId}, clusterId=${clusterId})`);

  const menuRes = await apiClient.getMenu(session, { menuConfigId, menuTempId: branchVerify.menuTempId, service: channel }, logger);
  record('getMenu', { menuConfigId }, menuRes);
  if (!menuRes.schema.valid) {
    const msg = `getMenu failed schema validation: ${menuRes.schema.reason}`;
    logger.error(`[MENU] ${msg}`);
    return buildFailedResult(channel, startedAt, msg, { categoryCount: 0, productCount: 0, offerCount: 0 }, { menuConfigId, clusterId });
  }
  const categories = apiClient.getPath(menuRes.data, 'data.categories') || [];
  const expectedCategoryCount = categories.length;
  logger.tag('MENU', `${expectedCategoryCount} categor${expectedCategoryCount === 1 ? 'y' : 'ies'} discovered for ${channel}`);

  const categoryResults = [];
  const products = [];
  for (let i = 0; i < categories.length; i++) {
    const cat = categories[i];
    await wait(CONFIG.DELAY_BETWEEN_REQUESTS);
    logger.tag('CATEGORY', `[CATEGORY ${i + 1}/${categories.length}] ${cat.name}`);
    let catRes;
    try {
      catRes = await withRetry(
        () => apiClient.getProductsByCategory(session, { categoryId: cat.id, cluster: clusterId, configId: menuConfigId, service: channel, menuTempId: branchVerify.menuTempId }, logger),
        CONFIG.MAX_RETRIES,
        logger,
        `getProductsByCategory(${cat.id})`
      );
    } catch (e) {
      catRes = { schema: { valid: false, reason: e.message }, error: e.message };
    }
    record(`getProductsByCategory-${cat.id}`, { id: cat.id }, catRes);

    if (catRes.schema && catRes.schema.valid) {
      const catProducts = apiClient.getPath(catRes.data, 'data.products') || [];
      categoryResults.push({ categoryId: cat.id, name: cat.name, status: 'SUCCESS', productCount: catProducts.length, error: null });
      for (const p of catProducts) {
        products.push({ ...p, __categoryId: cat.id, __categoryName: cat.name, __sourceEndpoint: '/api/getProductsByCategory' });
      }
      logger.tag('PRODUCTS', `${catProducts.length} product(s) collected for "${cat.name}"`);
    } else {
      const reason = (catRes.schema && catRes.schema.reason) || catRes.error || 'unknown error';
      categoryResults.push({ categoryId: cat.id, name: cat.name, status: 'FAILED', productCount: 0, error: reason });
      logger.error(`[CATEGORY] "${cat.name}" (id=${cat.id}) failed: ${reason}`);
    }
  }

  // Best-effort progressive promotions - never affects run status.
  let promotions = [];
  try {
    const homeRes = await apiClient.getHome(session, { menuConfigId, cluster: clusterId, menuTempId: branchVerify.menuTempId }, logger);
    record('getHome', { menuConfigId }, homeRes);
    if (homeRes.schema.valid) {
      const menuId = apiClient.getPath(homeRes.data, 'data.menuId');
      const promoRes = await apiClient.getProgressivePromotion(session, { orderType: channel, menuId, menuTempId: branchVerify.menuTempId, cluster: clusterId, configId: menuConfigId }, logger);
      record('getProgressivePromotion', { orderType: channel, menuId }, promoRes);
      if (promoRes.schema.valid) {
        // Live-confirmed 2026-08-05: response.data = {parentPromo, promolist,
        // headerText} where promolist is a MAP keyed by promoId (empty {}
        // when no progressive promotion is currently active for this
        // branch/channel) - not a bare array as first assumed. Handle both
        // shapes defensively since this endpoint's payload was reconstructed
        // (see api-map.md) and an empty result is a valid, common answer.
        const raw = apiClient.getPath(promoRes.data, 'data.promolist');
        promotions = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? Object.values(raw) : [];
        logger.tag('PROMOTIONS', `${promotions.length} progressive promotion(s) retrieved for ${channel}`);
      } else {
        logger.warn(`[PROMOTIONS] getProgressivePromotion failed schema validation (non-fatal): ${promoRes.schema.reason}`);
      }
    } else {
      logger.warn(`[PROMOTIONS] getHome failed schema validation (non-fatal, skipping progressive promotions): ${homeRes.schema.reason}`);
    }
  } catch (e) {
    logger.warn(`[PROMOTIONS] Skipping progressive promotions (non-fatal): ${e.message}`);
  }

  const successCategoryCount = categoryResults.filter((c) => c.status === 'SUCCESS').length;
  const completionPercentage = expectedCategoryCount > 0 ? Math.round((successCategoryCount / expectedCategoryCount) * 10000) / 100 : 0;
  let status;
  if (expectedCategoryCount === 0) status = 'FAILED';
  else if (successCategoryCount === expectedCategoryCount) status = 'SUCCESS';
  else if (successCategoryCount > 0) status = 'PARTIAL';
  else status = 'FAILED';

  const finishedAt = new Date().toISOString();
  logger.success(`[RUN] ${channel} completed with status=${status} (${successCategoryCount}/${expectedCategoryCount} categories, ${products.length} products, ${promotions.length} promotions)`);

  return {
    channel,
    status,
    startedAt,
    finishedAt,
    branchId: CONFIG.BRANCH.storeId,
    branchName: CONFIG.BRANCH.branchName,
    city: CONFIG.BRANCH.city,
    apiConfigId: menuConfigId || null,
    clusterId: clusterId || null,
    categories,
    categoryResults,
    expectedCategoryCount,
    categoryCount: successCategoryCount,
    completionPercentage,
    products,
    promotions,
    productCount: products.length,
    branchCurrentlyClosed: !!branchVerify.currentlyClosed,
    errorMessage: status === 'FAILED' ? 'All categories failed schema validation - see categoryResults' : status === 'PARTIAL' ? `${expectedCategoryCount - successCategoryCount} of ${expectedCategoryCount} categories failed - see categoryResults` : null,
  };
}

function buildFailedResult(channel, startedAt, errorMessage, counts, extra = {}) {
  return {
    channel,
    status: 'FAILED',
    startedAt,
    finishedAt: new Date().toISOString(),
    branchId: CONFIG.BRANCH.storeId,
    branchName: CONFIG.BRANCH.branchName,
    city: CONFIG.BRANCH.city,
    apiConfigId: extra.menuConfigId || null,
    clusterId: extra.clusterId || null,
    categories: [],
    categoryResults: [],
    expectedCategoryCount: 0,
    categoryCount: counts.categoryCount ?? 0,
    completionPercentage: 0,
    products: [],
    promotions: [],
    productCount: counts.productCount ?? 0,
    errorMessage,
  };
}

module.exports = { collectChannel, verifyBranchExists, resolveBranchForChannel };
