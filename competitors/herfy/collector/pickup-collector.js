'use strict';

const { collectChannel } = require('./channel-collector');

async function collectPickup(bootstrap, logger, opts) {
  return collectChannel('PICKUP', bootstrap, logger, opts);
}

module.exports = { collectPickup };
