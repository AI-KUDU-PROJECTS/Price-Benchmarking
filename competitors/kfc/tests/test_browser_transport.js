'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const apiClient = require('../collector/api-client');
const http = require('../collector/http-client');

test('KFC API calls prefer the live browser transport over direct Node HTTPS', async () => {
  const original = http.request;
  const seen = [];
  http.request = async () => {
    throw new Error('direct HTTPS transport must not be used');
  };

  try {
    const session = {
      cookies: [{ name: 'guest', value: 'session' }],
      headers: { deviceid: 'device-1' },
      browserRequest: async (request) => {
        seen.push(request);
        return {
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: '{"data":{"storeId":143}}',
          json: { data: { storeId: 143 } },
          parseError: null,
        };
      },
    };

    const result = await apiClient.call(session, {
      method: 'POST',
      path: '/api/getNewStore',
      payload: { lat: 24.7, lng: 46.6 },
      label: 'getNewStore',
    });

    assert.equal(result.ok, true);
    assert.equal(result.data.data.storeId, 143);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].method, 'POST');
    assert.match(seen[0].url, /\/api\/getNewStore$/);
    assert.deepEqual(seen[0].body, { lat: 24.7, lng: 46.6 });
  } finally {
    http.request = original;
  }
});
