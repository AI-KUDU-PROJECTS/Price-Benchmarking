'use strict';

const { collectChannel } = require('./channel-collector');

async function collectDelivery(bootstrap, logger, opts) {
  return collectChannel('DELIVERY', bootstrap, logger, opts);
}

module.exports = { collectDelivery };
