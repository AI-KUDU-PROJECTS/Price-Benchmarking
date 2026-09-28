'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const apiClient = require('../collector/api-client');
const CONFIG = require('../collector/config');
const { resolveBranchForChannel } = require('../collector/channel-collector');

test('Hardees Pickup uses only the verified configured branch when getNewStore returns zero', async () => {
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
    assert.deepEqual(fallback, {
      ok: true,
      storeId: CONFIG.BRANCH.storeId,
      catalogFallback: true,
    });
    assert.match(warnings[0], /read-only catalog collection/);

    const unsupported = await resolveBranchForChannel({}, 'PICKUP', logger, {
      storeRecord: { storeId: CONFIG.BRANCH.storeId, cmsStatus: 1, services: { tak: 0 } },
    });
    assert.equal(unsupported.ok, false);
    assert.match(unsupported.error, /does not advertise Pickup support/);

    apiClient.getNewStore = async () => ({
      schema: { valid: true, reason: null },
      data: { data: { storeId: CONFIG.BRANCH.storeId + 1 } },
    });
    const wrongBranch = await resolveBranchForChannel({}, 'PICKUP', logger, verifiedPickupStore);
    assert.equal(wrongBranch.ok, false);
    assert.match(wrongBranch.error, /nearest pickup branch.*changed/);
  } finally {
    apiClient.getNewStore = original;
  }
});
