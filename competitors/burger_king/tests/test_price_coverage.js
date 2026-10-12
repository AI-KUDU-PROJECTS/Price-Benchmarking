'use strict';

process.env.DELAY_BETWEEN_REQUESTS = '0';

const test = require('node:test');
const assert = require('node:assert/strict');

const apiClient = require('../collector/api-client');
const priceScraper = require('../collector/price-scraper');
const CONFIG = require('../collector/config');
const { collectChannel } = require('../collector/channel-collector');
const { applyStoreMenuPrices } = require('../collector/price-resolver');

const logger = { tag() {}, warn() {}, info() {} };
const ok = (data) => ({ ok: true, status: 200, schema: { valid: true, reason: null }, data });

function menu(count) {
  const options = Array.from({ length: count }, (_, index) => ({
    _id: `item-${index}`,
    _type: 'item',
    name: { locale: `Item ${index}` },
  }));
  return ok({ Menu: { options: [{ _id: 'section-1', _type: 'section', name: { locale: 'Burgers' }, options }] } });
}

async function collectWith(storeMenuResponse, count = 10) {
  const originals = { ...apiClient };
  const originalScrape = priceScraper.scrapePricesForChannel;
  try {
    apiClient.getRestaurants = async () => ok({
      restaurants: { nodes: [{ storeId: CONFIG.BRANCH.storeId, mobileOrderingStatus: 'live', isAvailable: true }] },
    });
    apiClient.getRestaurant = async () => ok({ restaurant: { available: true } });
    apiClient.featureMenu = async () => ok({ FeatureMenu: { defaultMenu: { _id: 'menu-1' } } });
    apiClient.getMenuSections = async () => menu(count);
    apiClient.storeMenu = async () => storeMenuResponse;
    apiClient.plusData = async () => ok({ plus: [] });
    priceScraper.scrapePricesForChannel = async () => new Map();
    return await collectChannel('PICKUP', logger);
  } finally {
    Object.assign(apiClient, originals);
    priceScraper.scrapePricesForChannel = originalScrape;
  }
}

test('storeMenu isAvailable=false marks the item unavailable instead of unpriced', () => {
  const products = [{ _id: 'a' }, { _id: 'b' }, { _id: 'c' }];
  applyStoreMenuPrices(products, [
    { id: 'a', isAvailable: true, price: { default: 1500, min: 1500, max: 1500 } },
    { id: 'b', isAvailable: false, price: { default: 0, min: 0, max: 0 } },
  ]);
  assert.equal(products[0].__available, true);
  assert.equal(products[0].__price, 15);
  assert.equal(products[1].__available, false);
  assert.equal(products[1].__price, undefined);
  assert.equal(products[2].__available, undefined);
});

test('a channel whose prices collapsed is PARTIAL, not SUCCESS', async () => {
  const result = await collectWith({ ok: false, status: 500, schema: { valid: false, reason: 'http 500' }, data: null });
  assert.equal(result.status, 'PARTIAL');
  assert.match(result.errorMessage, /0\/10 available products have a price/);
});

test('unavailable items do not count against price coverage', async () => {
  const entities = Array.from({ length: 10 }, (_, index) => (
    index < 4
      ? { id: `item-${index}`, isAvailable: false, price: { default: 0, min: 0, max: 0 } }
      : { id: `item-${index}`, isAvailable: true, price: { default: 2000, min: 2000, max: 2000 } }
  ));
  const result = await collectWith(ok({ storeMenu: entities }));
  assert.equal(result.status, 'SUCCESS');
  assert.equal(result.errorMessage, null);
});
