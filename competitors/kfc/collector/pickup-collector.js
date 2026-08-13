'use strict';

/**
 * collector/pickup-collector.js
 * ---------------------------------------------------------------------
 * PICKUP channel entry point, per the required flow:
 *
 *   getMenuConfig(orderType=PICKUP) -> obtain configId and clusterId
 *   -> getMenu -> extract all category IDs
 *   -> loop through getProductsByCategory
 *   -> save Channel=PICKUP
 *
 * All of the actual logic is shared with delivery-collector.js in
 * channel-collector.js (both channels are the same shape end to end,
 * differing only in how the branch is resolved - getNewStore here vs.
 * validateLocation for delivery) - this file exists as a named, explicit
 * entry point so `Channel=PICKUP` is never ambiguous to a reader of the
 * collector, matching the required project structure.
 * ---------------------------------------------------------------------
 */

const { collectChannel } = require('./channel-collector');

async function collectPickup(session, logger, opts) {
  return collectChannel(session, 'PICKUP', logger, opts);
}

module.exports = { collectPickup };
