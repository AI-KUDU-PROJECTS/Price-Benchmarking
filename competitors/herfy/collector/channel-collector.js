'use strict';

/**
 * collector/channel-collector.js
 * ---------------------------------------------------------------------
 * Shared PICKUP/DELIVERY collection logic - mirrors the shape of
 * competitors/kfc's and competitors/burger_king's channel-collector.js.
 * Herfy's menu-ref CDN JSON returns the ENTIRE category+item+modifier
 * tree in one request, and it is NOT branch- or channel-scoped (see
 * research/api-map/api-map.md), so this collector fetches the menu once
 * per run and reuses it for both channels, filtering only the small
 * per-item disable-for-pickup/disable-for-delivery flags per channel.
 * Real prices come directly from the API response - no DOM-scrape
 * workaround is needed for this brand (unlike Burger King).
 * ---------------------------------------------------------------------
 */

const CONFIG = require('./config');
const apiClient = require('./api-client');

/**
 * Branch existence check (equivalent of KFC's getStoreList / Burger
 * King's verifyBranchExists): is the configured locationId still a real,
 * listed, active branch nearby its own coordinates?
 */
async function verifyBranchExists(appKey, logger) {
  const res = await apiClient.getLocationsNearby({ lat: CONFIG.BRANCH.latitude, long: CONFIG.BRANCH.longitude, limit: 999, appKey }, logger);
  if (!res.ok || !res.schema.valid) {
    return { ok: false, reason: `getLocationsNearby failed or malformed (status=${res.status}, schema=${res.schema.reason || 'n/a'})`, raw: res };
  }
  const nodes = res.data.data || [];
  const match = nodes.find((n) => String(n.id) === String(CONFIG.BRANCH.locationId));
  if (!match) {
    return { ok: false, reason: `locationId ${CONFIG.BRANCH.locationId} (${CONFIG.BRANCH.branchName}) not found nearby its own configured coordinates - branch may have closed permanently or the id/coordinates in .env are wrong`, raw: res };
  }
  const attrs = match.attributes || {};
  if (attrs.status !== 'active') {
    return { ok: false, reason: `locationId ${CONFIG.BRANCH.locationId} has status="${attrs.status}" (expected "active")`, raw: res };
  }
  const currentlyClosed = attrs['is-open'] === false;
  if (currentlyClosed) {
    logger.tag('BRANCH', `Branch "${CONFIG.BRANCH.branchName}" currently shows is-open=false - informational only (real-time open/closed state), not treated as a FAILED reason.`);
  }
  return { ok: true, location: match, currentlyClosed, raw: res };
}

/** Channel-specific availability check - the one place PICKUP and DELIVERY genuinely differ. */
async function resolveBranchForChannel(channel, appKey, logger) {
  const res = await apiClient.getLocationById({ locationId: CONFIG.BRANCH.locationId, appKey }, logger);
  if (!res.ok || !res.schema.valid) {
    return { ok: false, reason: `getLocationById failed (status=${res.status}, schema=${res.schema.reason || 'n/a'})`, raw: res };
  }
  const attrs = (res.data.data && res.data.data.attributes) || {};
  if (channel === 'PICKUP') {
    if (!attrs['pickup-enabled']) {
      return { ok: false, reason: 'Branch does not have pickup-enabled at all (structural, not real-time)', raw: res };
    }
    if (attrs['is-open-pickup'] === false) {
      logger.tag('BRANCH', 'Branch shows is-open-pickup=false at this moment - informational (real-time hours), collection continues.');
    }
    return { ok: true, hours: attrs, raw: res };
  }

  // DELIVERY
  if (!attrs['delivery-enabled']) {
    return { ok: false, reason: 'Branch does not have delivery-enabled at all (structural, not real-time)', raw: res };
  }
  if (attrs['is-open-deliver'] === false) {
    logger.tag('BRANCH', 'Branch shows is-open-deliver=false at this moment - informational (real-time hours), collection continues.');
  }
  return { ok: true, hours: attrs, raw: res };
}

/**
 * Resolves an item's modifier-groups[] reference list into full
 * {id, name, nameAr, min, max, modifiers:[{id, name, nameAr, price}]}
 * records, using the menu response's `included.modifierGroups`/
 * `included.modifiers` side-tables. Self-contained on the product itself
 * (matches the pattern every other competitor in this repo uses -
 * nothing needing a separate side-table lookup survives past this
 * flatten step).
 */
function resolveOptionGroups(modifierGroupRefs, groupsById, modifiersById) {
  const out = [];
  for (const ref of modifierGroupRefs || []) {
    const group = groupsById.get(ref.id);
    if (!group) continue;
    const attrs = group.attributes || {};
    const modifiers = [];
    for (const modRef of ref.modifiers || []) {
      const mod = modifiersById.get(modRef.id);
      if (!mod) continue;
      const mAttrs = mod.attributes || {};
      modifiers.push({
        id: mod.id,
        name: mAttrs.name && mAttrs.name['en-us'],
        nameAr: mAttrs.name && mAttrs.name['ar-sa'],
        price: typeof mAttrs.price === 'number' ? mAttrs.price : null,
      });
    }
    out.push({
      id: group.id,
      name: attrs.name && attrs.name['en-us'],
      nameAr: attrs.name && attrs.name['ar-sa'],
      min: attrs.minimum,
      max: attrs.maximum,
      modifiers,
    });
  }
  return out;
}

/** Flattens the menu-ref response's `data[]` (category-items) into {categories, products}, resolving modifier references onto each product. */
function flattenMenu(menuData) {
  const included = menuData.included || {};
  const groupsById = new Map((included.modifierGroups || []).map((g) => [g.id, g]));
  const modifiersById = new Map((included.modifiers || []).map((m) => [m.id, m]));

  const categories = [];
  const products = [];

  for (const entry of menuData.data || []) {
    if (!entry || entry.type !== 'category-items') continue;
    const cat = (entry.attributes && entry.attributes.category) || {};
    const categoryId = cat.id != null ? cat.id : entry.id;
    const categoryName = cat.name && cat.name['en-us'];
    const categoryNameAr = cat.name && cat.name['ar-sa'];
    categories.push({ id: categoryId, name: categoryName, nameAr: categoryNameAr, enabled: !!cat.enabled, displayOrder: cat['display-order'] });

    const items = (entry.attributes && entry.attributes.items) || [];
    for (const item of items) {
      if (!item) continue;
      products.push({
        ...item,
        __optionGroups: resolveOptionGroups(item['modifier-groups'], groupsById, modifiersById),
        __categoryId: categoryId,
        __categoryName: categoryName,
        __categoryNameAr: categoryNameAr,
        __sourceEndpoint: 'menu-ref',
      });
    }
  }

  return { categories, products };
}

function failedResult(channel, startedAt, branchCheck, errorMessage) {
  return {
    channel, status: 'FAILED', startedAt, finishedAt: new Date().toISOString(),
    branchId: CONFIG.BRANCH.locationId, branchName: CONFIG.BRANCH.branchName, city: CONFIG.BRANCH.city,
    apiConfigId: null, clusterId: null, categories: [], categoryResults: [], expectedCategoryCount: 0,
    categoryCount: 0, completionPercentage: 0, products: [], promotions: [], productCount: 0,
    branchCurrentlyClosed: (branchCheck && branchCheck.currentlyClosed) || false, errorMessage,
  };
}

/**
 * Runs the full collection for one channel: app bootstrap (passed in) ->
 * branch check -> channel-specific availability check -> menu fetch ->
 * flatten -> per-channel item filtering -> status computation.
 * `onRawResponse(name, data)` lets collect.js persist every raw API call
 * for provenance, matching every other competitor's contract.
 */
async function collectChannel(channel, bootstrap, logger, { onRawResponse } = {}) {
  const startedAt = new Date().toISOString();
  const record = (name, res) => { if (onRawResponse) onRawResponse(name, res); };

  const branchCheck = await verifyBranchExists(bootstrap.appKey, logger);
  record('getLocationsNearby', branchCheck.raw);
  if (!branchCheck.ok) return failedResult(channel, startedAt, null, branchCheck.reason);

  const channelCheck = await resolveBranchForChannel(channel, bootstrap.appKey, logger);
  record(`resolveBranchFor${channel}`, channelCheck.raw);
  if (!channelCheck.ok) return failedResult(channel, startedAt, branchCheck, channelCheck.reason);

  const menuRes = await apiClient.getMenu({ menuRefUrl: bootstrap.menuRef }, logger);
  record('getMenu', menuRes);
  if (!menuRes.ok || !menuRes.schema.valid) {
    return failedResult(channel, startedAt, branchCheck, `getMenu failed (status=${menuRes.status}, schema=${menuRes.schema.reason || 'n/a'})`);
  }

  const { categories, products: allProducts } = flattenMenu(menuRes.data);
  const disableFlag = channel === 'PICKUP' ? 'disable-for-pickup' : 'disable-for-delivery';
  const products = allProducts.filter((p) => !p[disableFlag]);
  logger.tag(
    'MENU',
    `Flattened ${categories.length} categor${categories.length === 1 ? 'y' : 'ies'} / ${allProducts.length} item entr${allProducts.length === 1 ? 'y' : 'ies'} from the menu-ref CDN JSON` +
      (products.length !== allProducts.length ? ` (${allProducts.length - products.length} excluded for channel=${channel} via ${disableFlag})` : '')
  );

  const categoryResults = categories.map((c) => ({
    categoryId: c.id,
    name: c.name,
    status: 'SUCCESS',
    productCount: products.filter((p) => p.__categoryId === c.id).length,
    error: null,
  }));

  const status = products.length > 0 ? 'SUCCESS' : 'FAILED';

  return {
    channel,
    status,
    startedAt,
    finishedAt: new Date().toISOString(),
    branchId: CONFIG.BRANCH.locationId,
    branchName: CONFIG.BRANCH.branchName,
    city: CONFIG.BRANCH.city,
    apiConfigId: String(bootstrap.defaultMenuId),
    clusterId: bootstrap.applicationId != null ? String(bootstrap.applicationId) : null,
    categories,
    categoryResults,
    expectedCategoryCount: categories.length,
    categoryCount: categories.length,
    completionPercentage: categories.length ? 100 : 0,
    products,
    promotions: [],
    productCount: products.length,
    branchCurrentlyClosed: branchCheck.currentlyClosed,
    errorMessage: status === 'FAILED' ? 'Menu returned zero eligible products for this channel' : null,
  };
}

module.exports = { collectChannel, verifyBranchExists, resolveBranchForChannel, flattenMenu, resolveOptionGroups };
