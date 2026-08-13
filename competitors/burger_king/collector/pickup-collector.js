'use strict';

const { collectChannel } = require('./channel-collector');

async function collectPickup(logger, opts) {
  return collectChannel('PICKUP', logger, opts);
}

module.exports = { collectPickup };
