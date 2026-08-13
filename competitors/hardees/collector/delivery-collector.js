'use strict';

/**
 * collector/delivery-collector.js
 * ---------------------------------------------------------------------
 * DELIVERY channel entry point, per the required flow:
 *
 *   getMenuConfig(orderType=DELIVERY) -> obtain configId and clusterId
 *   -> getMenu -> extract all category IDs
 *   -> loop through getProductsByCategory
 *   -> save Channel=DELIVERY
 *
 * See pickup-collector.js for why the shared logic lives in
 * channel-collector.js. The only difference here is branch resolution
 * uses validateLocation (delivery serviceability for the configured
 * coordinates) instead of getNewStore.
 * ---------------------------------------------------------------------
 */

const { collectChannel } = require('./channel-collector');

async function collectDelivery(session, logger, opts) {
  return collectChannel(session, 'DELIVERY', logger, opts);
}

module.exports = { collectDelivery };
