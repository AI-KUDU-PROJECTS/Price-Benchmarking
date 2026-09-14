'use strict';

/**
 * collector/channel-collector.js
 * ---------------------------------------------------------------------
 * Shared PICKUP/DELIVERY collection logic - mirrors the shape of
 * competitors/kfc/collector/channel-collector.js. Unlike KFC, Burger
 * King's GetMenuSections call returns the ENTIRE category+product tree
 * in one request (no per-category follow-up calls, and the menu content
 * is not channel-scoped - see research/api-map/api-map.md), so this
 * collector fetches the menu once and reuses it for both channels.
 * Per-channel prices come from the storeMenu GraphQL API (primary), with
 * a DOM scrape fallback for any product storeMenu leaves unpriced.
 * ---------------------------------------------------------------------
 */

const CONFIG = require('./config');
const apiClient = require('./api-client');
const priceScraper = require('./price-scraper');
const priceResolver = require('./price-resolver');
const http = require('./http-client');

/**
 * Branch existence check (equivalent of KFC's getStoreList/cmsStatus
 * check): is the configured storeId still a real, listed branch? Uses
 * GetRestaurants (the directory), not GetRestaurant's real-time
 * available flag, for the same reason KFC checks cmsStatus rather than
 * active/sdmStatus - a branch's real-time open/closed state is
 * informational, never a reason to fail the whole run.
 */
async function verifyBranchExists(logger) {
  const res = await apiClient.getRestaurants({ lat: CONFIG.BRANCH.latitude, lng: CONFIG.BRANCH.longitude, searchRadius: 20000, filter: 'NEARBY' }, logger);
  if (!res.ok || !res.schema.valid) {
    return { ok: false, reason: `getRestaurants failed or malformed (status=${res.status}, schema=${res.schema.reason || 'n/a'})`, raw: res };
  }
  const nodes = (res.data.restaurants && res.data.restaurants.nodes) || [];
  const match = nodes.find((n) => String(n.storeId) === String(CONFIG.BRANCH.storeId));
  if (!match) {
    return { ok: false, reason: `storeId ${CONFIG.BRANCH.storeId} (${CONFIG.BRANCH.branchName}) not found within 20km of its own configured coordinates - branch may have closed permanently or the id/coordinates in .env are wrong`, raw: res };
  }
  const currentlyClosed = match.mobileOrderingStatus !== 'live' || match.isAvailable === false;
  if (currentlyClosed) {
    logger.tag('BRANCH', `Branch "${CONFIG.BRANCH.branchName}" currently shows mobileOrderingStatus=${match.mobileOrderingStatus}, isAvailable=${match.isAvailable} - informational only (real-time open/closed state), not treated as a FAILED reason.`);
  }
  return { ok: true, restaurant: match, currentlyClosed, raw: res };
}

/** Channel-specific availability check - the one place PICKUP and DELIVERY genuinely differ. */
async function resolveBranchForChannel(channel, logger) {
  if (channel === 'PICKUP') {
    const res = await apiClient.getRestaurant({ storeId: CONFIG.BRANCH.storeId }, logger);
    if (!res.ok || !res.schema.valid) {
      return { ok: false, reason: `getRestaurant failed for pickup check (status=${res.status})`, raw: res };
    }
    if (res.data.restaurant.available === false) {
      logger.tag('BRANCH', 'Branch shows available=false for pickup at this moment - informational (real-time hours), collection continues.');
    }
    return { ok: true, hours: res.data.restaurant, raw: res };
  }

  // DELIVERY: use the branch's own coordinates with placeholder/test
  // address text (never a real customer address - see README "Security
  // & compliance").
  const res = await apiClient.deliveryRestaurant(
    {
      addressLine1: `${CONFIG.BRANCH.branchName} (TEST VALUE)`,
      city: CONFIG.BRANCH.city,
      route: 'Test Street (TEST VALUE)',
      streetNumber: '1',
      zip: '00000',
      latitude: CONFIG.BRANCH.latitude,
      longitude: CONFIG.BRANCH.longitude,
    },
    logger
  );
  if (!res.ok || !res.schema.valid) {
    return { ok: false, reason: `deliveryRestaurant failed (status=${res.status}, schema=${res.schema.reason || 'n/a'})`, raw: res };
  }
  const dr = res.data.deliveryRestaurant;
  const deliverable = dr.storeStatus === 'OPEN' && dr.quote === 'QUOTE_SUCCESSFUL';
  if (!deliverable) {
    return {
      ok: false,
      reason: `Not deliverable right now: storeStatus=${dr.storeStatus}, quote=${dr.quote}${dr.unavailabilityReason ? `, reason=${dr.unavailabilityReason}` : ''}`,
      deliveryInfo: dr,
      raw: res,
    };
  }
  return { ok: true, deliveryInfo: dr, raw: res };
}

/** Recursively flattens the Sanity menu tree into {categories, products}. Sections can nest sections. */
function flattenMenuTree(sections) {
  const categories = [];
  const products = [];

  function visitProduct(node, categoryId, categoryName) {
    products.push({ ...node, __categoryId: categoryId, __categoryName: categoryName, __sourceEndpoint: 'GetMenuSections' });
  }

  function visitSection(section, depth) {
    if (!section || section._type !== 'section') return;
    const categoryId = section._id;
    const categoryName = (section.name && section.name.locale) || null;
    categories.push({
      id: categoryId,
      name: categoryName,
      nameAr: section.name && section.name._locFb,
      showInStaticMenu: !!section.showInStaticMenu,
      depth,
    });
    for (const child of section.options || []) {
      if (!child || !child._type) continue;
      if (child._type === 'section') {
        visitSection(child, depth + 1);
      } else if (child._type === 'item' || child._type === 'combo' || child._type === 'picker') {
        visitProduct(child, categoryId, categoryName);
      }
    }
  }

  for (const top of sections || []) visitSection(top, 0);
  return { categories, products };
}

/**
 * Runs the full collection for one channel: branch check -> menu fetch ->
 * price scrape -> merge -> status computation. `onRawResponse(name, data)`
 * lets collect.js persist every raw API call for provenance, matching
 * KFC's contract.
 */
async function collectChannel(channel, logger, { onRawResponse } = {}) {
  const startedAt = new Date().toISOString();
  const record = (name, res) => { if (onRawResponse) onRawResponse(name, res); };

  const branchCheck = await verifyBranchExists(logger);
  record('getRestaurants', branchCheck.raw);
  if (!branchCheck.ok) {
    return {
      channel, status: 'FAILED', startedAt, finishedAt: new Date().toISOString(),
      branchId: CONFIG.BRANCH.storeId, branchName: CONFIG.BRANCH.branchName, city: CONFIG.BRANCH.city,
      apiConfigId: null, clusterId: null, categories: [], categoryResults: [], expectedCategoryCount: 0,
      categoryCount: 0, completionPercentage: 0, products: [], promotions: [], productCount: 0,
      branchCurrentlyClosed: false, errorMessage: branchCheck.reason,
    };
  }

  const channelCheck = await resolveBranchForChannel(channel, logger);
  record(`resolveBranchFor${channel}`, channelCheck.raw);
  if (!channelCheck.ok) {
    return {
      channel, status: 'FAILED', startedAt, finishedAt: new Date().toISOString(),
      branchId: CONFIG.BRANCH.storeId, branchName: CONFIG.BRANCH.branchName, city: CONFIG.BRANCH.city,
      apiConfigId: null, clusterId: null, categories: [], categoryResults: [], expectedCategoryCount: 0,
      categoryCount: 0, completionPercentage: 0, products: [], promotions: [], productCount: 0,
      branchCurrentlyClosed: branchCheck.currentlyClosed, errorMessage: channelCheck.reason,
    };
  }

  const featureMenuRes = await apiClient.featureMenu(logger);
  record('featureMenu', featureMenuRes);
  const menuId = featureMenuRes.ok && featureMenuRes.schema.valid ? featureMenuRes.data.FeatureMenu.defaultMenu._id : null;
  if (!menuId) {
    return {
      channel, status: 'FAILED', startedAt, finishedAt: new Date().toISOString(),
      branchId: CONFIG.BRANCH.storeId, branchName: CONFIG.BRANCH.branchName, city: CONFIG.BRANCH.city,
      apiConfigId: null, clusterId: null, categories: [], categoryResults: [], expectedCategoryCount: 0,
      categoryCount: 0, completionPercentage: 0, products: [], promotions: [], productCount: 0,
      branchCurrentlyClosed: branchCheck.currentlyClosed, errorMessage: 'featureMenu did not resolve a menu id',
    };
  }

  const menuRes = await apiClient.getMenuSections({ menuId }, logger);
  record('getMenuSections', menuRes);
  if (!menuRes.ok || !menuRes.schema.valid) {
    return {
      channel, status: 'FAILED', startedAt, finishedAt: new Date().toISOString(),
      branchId: CONFIG.BRANCH.storeId, branchName: CONFIG.BRANCH.branchName, city: CONFIG.BRANCH.city,
      apiConfigId: menuId, clusterId: null, categories: [], categoryResults: [], expectedCategoryCount: 0,
      categoryCount: 0, completionPercentage: 0, products: [], promotions: [], productCount: 0,
      branchCurrentlyClosed: branchCheck.currentlyClosed, errorMessage: `getMenuSections failed (status=${menuRes.status}, schema=${menuRes.schema.reason || 'n/a'})`,
    };
  }

  const { categories, products } = flattenMenuTree(menuRes.data.Menu.options);
  logger.tag('MENU', `Flattened ${categories.length} categor${categories.length === 1 ? 'y' : 'ies'} / ${products.length} product entr${products.length === 1 ? 'y' : 'ies'} from GetMenuSections`);

  await http.wait(CONFIG.DELAY_BETWEEN_REQUESTS);

  // Primary prices: store-scoped storeMenu API (Sanity _id → cents).
  const serviceMode = channel === 'DELIVERY' ? 'delivery' : 'pickup';
  const storeMenuRes = await apiClient.storeMenu({
    storeId: CONFIG.BRANCH.storeId,
    serviceMode,
  }, logger);
  record('storeMenu', storeMenuRes);
  let apiPriced = 0;
  if (storeMenuRes.ok && storeMenuRes.schema.valid) {
    const stats = priceResolver.applyStoreMenuPrices(products, storeMenuRes.data.storeMenu);
    apiPriced = stats.priced;
    logger.tag('STORE-MENU', `Priced ${stats.priced}/${products.length} products via storeMenu (${stats.matched} id matches, ${stats.storeEntityCount} entities, serviceMode=${serviceMode})`);
  } else {
    logger.tag('STORE-MENU', `storeMenu failed (status=${storeMenuRes.status}, schema=${storeMenuRes.schema && storeMenuRes.schema.reason || 'n/a'}) - falling back to DOM scrape for all prices`);
  }

  // Optional PLU map kept for audit / future zero-price fill (not required for the common path).
  const plusRes = await apiClient.plusData({ storeId: CONFIG.BRANCH.storeId, serviceMode }, logger);
  record('plusData', plusRes);

  // DOM scrape only for products still missing __price after storeMenu.
  const needScrape = products.filter((p) => p.__price == null || p.__price === undefined);
  let scrapePriced = 0;
  if (needScrape.length > 0) {
    await http.wait(CONFIG.DELAY_BETWEEN_REQUESTS);
    const priceMap = await priceScraper.scrapePricesForChannel(channel, logger);
    for (const product of needScrape) {
      const name = (product.name && product.name.locale) || null;
      const price = name ? priceScraper.lookupPrice(priceMap, name) : null;
      if (price !== null) {
        product.__price = price;
        product.__price_source = 'dom-scrape';
        scrapePriced += 1;
      }
    }
    logger.tag('PRICE-SCRAPER', `DOM fallback filled ${scrapePriced}/${needScrape.length} remaining products in channel ${channel}`);
  } else {
    logger.tag('PRICE-SCRAPER', `Skipped DOM scrape - storeMenu priced every product in channel ${channel}`);
  }
  const pricedCount = products.filter((p) => p.__price != null).length;
  logger.tag('PRICE', `Total priced ${pricedCount}/${products.length} (storeMenu=${apiPriced}, dom-fallback=${scrapePriced})`);

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
    branchId: CONFIG.BRANCH.storeId,
    branchName: CONFIG.BRANCH.branchName,
    city: CONFIG.BRANCH.city,
    apiConfigId: menuId,
    clusterId: null,
    categories,
    categoryResults,
    expectedCategoryCount: categories.length,
    categoryCount: categories.length,
    completionPercentage: categories.length ? 100 : 0,
    products,
    promotions: [],
    productCount: products.length,
    branchCurrentlyClosed: branchCheck.currentlyClosed,
    errorMessage: status === 'FAILED' ? 'GetMenuSections returned zero products' : null,
  };
}

module.exports = { collectChannel, verifyBranchExists, resolveBranchForChannel, flattenMenuTree };
