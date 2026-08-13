'use strict';

const { collectChannel } = require('./channel-collector');

async function collectDelivery(logger, opts) {
  return collectChannel('DELIVERY', logger, opts);
}

module.exports = { collectDelivery };
