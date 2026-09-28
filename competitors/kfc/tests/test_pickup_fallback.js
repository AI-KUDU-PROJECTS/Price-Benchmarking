'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const apiClient = require('../collector/api-client');
const CONFIG = require('../collector/config');
const { resolveBranchForChannel } = require('../collector/channel-collector');

test('KFC Pickup uses only the verified configured branch when getNewStore returns zero', async () => {
  const original = apiClient.getNewStore;
  const warnings = [];
  const logger = { warn: (message) => warnings.push(message) };
  const verifiedPickupStore = {
    storeRecord: {
      storeId: CONFIG.BRANCH.storeId,
      cmsStatus: 1,
      services: { tak: 1 },
    },
  };

  try {
    apiClient.getNewStore = async () => ({
      schema: { valid: true, reason: null },
      data: { data: { storeId: 0 } },
    });
    const fallback = await resolveBranchForChannel({}, 'PICKUP', logger, verifiedPickupStore);
    assert.equal(fallback.ok, true);
    assert.equal(fallback.storeId, CONFIG.BRANCH.storeId);
    assert.equal(fallback.catalogFallback, true);
    assert.match(warnings[0], /read-only catalog collection/);
  } finally {
    apiClient.getNewStore = original;
  }
});
