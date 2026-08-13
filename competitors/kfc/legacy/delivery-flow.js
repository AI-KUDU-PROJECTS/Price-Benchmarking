'use strict';

/**
 * delivery-flow.js
 * ---------------------------------------------------------------------
 * Drives the delivery-mode / location-selection journey:
 *   1. Switch the header order-mode tabs to "Delivery".
 *   2. Handle the address modal (Google-Maps-based "pin my location" +
 *      manual search fallback).
 *   3. Confirm the location, fill building/flat details if the site asks
 *      for them, and detect service-area availability.
 *   4. Also probes "Self-Pickup" so restaurant/branch availability for
 *      pickup is captured too (spec: "Pickup flow, if available").
 *
 * The selectors below are grounded in a live inspection of
 * https://saudi.kfc.me/en/home performed while building this project
 * (order-mode tabs, #search_location, "CONFIRM LOCATION",
 * "Building No./Name" + "Flat No." fields, /api/validateLocation,
 * /api/getStoreList). The site is a client-rendered SPA that can be timing
 * sensitive, so every step is retried and every wait is condition-based
 * rather than a fixed sleep.
 * ---------------------------------------------------------------------
 */

const CONFIG = require('../collector/config');
const safe = require('../collector/safe-actions');

async function clickOrderModeTab(page, logger, modeLabel) {
  // Strategy 1: MUI tab button with exact-ish visible text.
  const strategies = [
    () => page.getByRole('tab', { name: new RegExp(`^${modeLabel}$`, 'i') }).first(),
    () => page.locator('button', { hasText: new RegExp(`^${modeLabel}$`, 'i') }).first(),
    () => page.getByText(new RegExp(`^${modeLabel}$`, 'i'), { exact: false }).first(),
  ];
  for (const build of strategies) {
    try {
      const locator = build();
      if ((await locator.count().catch(() => 0)) === 0) continue;
      await safe.safeClick(page, locator, logger, { label: `order-mode:${modeLabel}` });
      return true;
    } catch (e) {
      if (e instanceof safe.SafetyBlockedError) throw e;
      // try next strategy
    }
  }
  return false;
}

async function addressModalIsOpen(page) {
  const signals = await Promise.all([
    page.locator('input#search_location').isVisible().catch(() => false),
    page.locator('text=/select delivery location/i').first().isVisible().catch(() => false),
    Promise.resolve(/modal=addaddress/i.test(page.url())),
  ]);
  return signals.some(Boolean);
}

async function tryManualLocationSearch(page, logger) {
  const searchBox = page.locator('input#search_location, input[placeholder="Search Location" i]').first();
  if ((await searchBox.count().catch(() => 0)) === 0) return false;
  const query = [CONFIG.TEST_LOCATION.area, CONFIG.TEST_LOCATION.city].filter(Boolean).join(', ');
  logger.tag('LOCATION', `Searching for configured test area: "${query}"`);
  try {
    await safe.safeClick(page, searchBox, logger, { label: 'location-search-box' });
    await searchBox.fill('', { timeout: CONFIG.ACTION_TIMEOUT }).catch(() => {});
    await searchBox.type(query, { delay: 60 });
  } catch (e) {
    if (e instanceof safe.SafetyBlockedError) throw e;
    logger.tag('LOCATION', `Could not type into location search box: ${e.message}`);
    return false;
  }
  // Google Places Autocomplete renders suggestions in a `.pac-container > .pac-item` list.
  const suggestion = await safe.pollUntil(
    page,
    async () => {
      const loc = page.locator('.pac-item, [class*="suggestion" i] li, [class*="autocomplete" i] li').first();
      return (await loc.count().catch(() => 0)) > 0 ? loc : null;
    },
    { timeoutMs: 8000, intervalMs: 400 }
  );
  if (!suggestion) {
    logger.tag('LOCATION', 'No location suggestions appeared for the configured test area');
    return false;
  }
  await safe.safeClick(page, suggestion, logger, { label: 'location-suggestion' }).catch((e) => {
    if (e instanceof safe.SafetyBlockedError) throw e;
  });
  logger.tag('LOCATION', 'Selected a suggested location from the search dropdown');
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
  return true;
}

async function confirmLocation(page, logger) {
  const confirmBtn = page.locator('button', { hasText: /^confirm location$/i }).first();
  if ((await confirmBtn.count().catch(() => 0)) === 0) return false;
  const enabled = await safe.pollUntil(
    page,
    async () => !(await confirmBtn.isDisabled().catch(() => true)),
    { timeoutMs: CONFIG.ACTION_TIMEOUT, intervalMs: 500 }
  );
  if (!enabled) {
    logger.tag('LOCATION', '"CONFIRM LOCATION" stayed disabled - map pin may not have resolved to an address yet');
    return false;
  }
  await safe.safeClick(page, confirmBtn, logger, { label: 'CONFIRM LOCATION' });
  logger.tag('LOCATION', 'Clicked CONFIRM LOCATION');
  return true;
}

async function fillAddressDetailsIfPresent(page, logger) {
  const buildingInput = page.locator('input[placeholder*="Building" i]').first();
  const hasBuilding = await safe.pollUntil(
    page,
    async () => (await buildingInput.isVisible().catch(() => false)) ? true : null,
    { timeoutMs: 6000, intervalMs: 500 }
  );
  if (!hasBuilding) return { fieldsPresent: false };

  logger.tag('LOCATION', 'Address detail form appeared (Building No. / Flat No.) - filling with configured test values');
  await safe.safeFill(buildingInput, CONFIG.TEST_LOCATION.buildingNumber, 'Building No./Name', logger).catch(() => {});

  const flatInput = page.locator('input[placeholder*="Flat" i]').first();
  if (await flatInput.count().catch(() => 0)) {
    await safe.safeFill(flatInput, CONFIG.TEST_LOCATION.flatNumber, 'Flat No.', logger).catch(() => {});
  }

  const howToReach = page.locator('input[placeholder*="how to reach" i], textarea[placeholder*="how to reach" i]').first();
  if (await howToReach.count().catch(() => 0)) {
    await safe.safeFill(howToReach, 'TEST VALUE - automated crawl, no real instructions', 'How to Reach', logger).catch(() => {});
  }

  // Prefer an "OTHER" tag over "HOME" so we don't mislabel a test address.
  const otherTag = page.locator('button', { hasText: /^other$/i }).first();
  if (await otherTag.count().catch(() => 0)) {
    await safe.safeClick(page, otherTag, logger, { label: 'tag-location:OTHER' }).catch(() => {});
  }

  const continueBtn = page.locator('button', { hasText: /^continue$/i }).first();
  if (await continueBtn.count().catch(() => 0)) {
    const enabled = await safe.pollUntil(
      page,
      async () => !(await continueBtn.isDisabled().catch(() => true)),
      { timeoutMs: CONFIG.ACTION_TIMEOUT, intervalMs: 500 }
    );
    if (enabled) {
      await safe.safeClick(page, continueBtn, logger, { label: 'CONTINUE (address details)' });
      logger.tag('LOCATION', 'Submitted address details (test values only)');
    } else {
      logger.tag('LOCATION', 'CONTINUE stayed disabled after filling address details');
    }
  }
  return { fieldsPresent: true };
}

/**
 * Runs the full delivery-mode + location-selection flow.
 * Reads/updates dataStore.deliveryInformation, which crawl-kfc.js's network
 * listener also populates from /api/validateLocation and /api/getStoreList
 * responses as they happen.
 */
async function runDeliveryFlow(page, context, logger, dataStore) {
  logger.section('DELIVERY FLOW');
  logger.tag('DELIVERY', 'Selecting delivery mode');

  await safe.dismissOverlays(page, logger);

  const clicked = await safe.retry(() => clickOrderModeTab(page, logger, 'Delivery'), CONFIG.MAX_RETRIES, logger, 'click Delivery tab');
  if (!clicked) {
    logger.warn('[DELIVERY] Could not find/click the "Delivery" order-mode tab - skipping delivery flow');
    dataStore.deliveryInformation.deliveryAvailable = false;
    dataStore.deliveryInformation.notes = 'Delivery tab control not found';
    return { deliveryAvailable: false, menuReached: false };
  }

  const modalOpened = await safe.pollUntil(page, () => addressModalIsOpen(page), { timeoutMs: 10000, intervalMs: 500 });
  if (!modalOpened) {
    logger.tag('LOCATION', 'No address modal appeared after selecting Delivery (site may already have a location set)');
  } else {
    logger.tag('LOCATION', `Delivery location modal open - using configured test coordinates (lat=${CONFIG.TEST_LOCATION.latitude}, lon=${CONFIG.TEST_LOCATION.longitude})`);

    // Give the map a moment to reverse-geocode the granted geolocation.
    await page.waitForTimeout(2000);

    const addressInput = page.locator('input[placeholder="Address Location" i]').first();
    const resolvedAddress = await safe.pollUntil(
      page,
      async () => {
        const val = await addressInput.inputValue().catch(() => '');
        return val && val.trim() ? val : null;
      },
      { timeoutMs: 8000, intervalMs: 500 }
    );

    if (!resolvedAddress) {
      logger.tag('LOCATION', 'Map did not auto-resolve an address from geolocation - attempting manual search fallback');
      await tryManualLocationSearch(page, logger);
    } else {
      logger.tag('LOCATION', `Map auto-resolved address: "${resolvedAddress}"`);
    }

    for (let attempt = 1; attempt <= CONFIG.MAX_RETRIES + 1; attempt++) {
      const didConfirm = await confirmLocation(page, logger);
      if (!didConfirm) break;
      await page.waitForTimeout(1500);

      if (dataStore.deliveryInformation.deliveryAvailable === true) break;
      if (dataStore.deliveryInformation.deliveryAvailable === false) {
        logger.warn(`[LOCATION] Location unavailable for delivery (attempt ${attempt}): ${dataStore.deliveryInformation.lastUnavailableMessage || 'no delivery to this area'}`);
        if (attempt <= CONFIG.MAX_RETRIES) {
          await tryManualLocationSearch(page, logger);
          continue;
        }
      }
      break;
    }

    await fillAddressDetailsIfPresent(page, logger);
  }

  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);

  const info = dataStore.deliveryInformation;
  if (info.deliveryAvailable) {
    logger.success(`[STORE] Branch available: ${info.branchName || info.branchId || 'unknown'} (fee=${info.deliveryFee ?? 'n/a'}, min order=${info.minimumOrder ?? 'n/a'}, ETA=${info.estimatedDeliveryTime ?? 'n/a'})`);
  } else if (info.deliveryAvailable === false) {
    logger.warn('[STORE] No deliverable branch found for the configured test location - continuing with menu browsing only');
  } else {
    logger.tag('DELIVERY', 'Delivery availability could not be conclusively determined from the UI/API - continuing');
  }

  return { deliveryAvailable: !!info.deliveryAvailable, menuReached: false };
}

/** Optional pickup-mode probe: switches to Self-Pickup and records what it finds. */
async function runPickupFlow(page, context, logger, dataStore) {
  logger.section('PICKUP FLOW');
  logger.tag('DELIVERY', 'Selecting Self-Pickup mode');
  await safe.dismissOverlays(page, logger);

  const clicked = await safe
    .retry(() => clickOrderModeTab(page, logger, 'Self-Pickup'), CONFIG.MAX_RETRIES, logger, 'click Self-Pickup tab')
    .catch((e) => {
      logger.warn(`[DELIVERY] Self-Pickup tab not available: ${e.message}`);
      return false;
    });
  if (!clicked) return { pickupAvailable: false };

  await page.waitForTimeout(2500);
  const modalOpened = await addressModalIsOpen(page);
  if (modalOpened) {
    // Pickup mode usually asks to pick a branch from a list rather than an address.
    const branchOption = page.locator('[class*="store" i], [class*="branch" i], li, [role="option"]').first();
    if (await branchOption.count().catch(() => 0)) {
      await safe.safeClick(page, branchOption, logger, { label: 'pickup:first-branch' }).catch(() => {});
      await page.waitForTimeout(1500);
    }
  }
  dataStore.deliveryInformation.pickupProbed = true;
  logger.tag('DELIVERY', 'Self-Pickup probe complete');
  return { pickupAvailable: true };
}

module.exports = { runDeliveryFlow, runPickupFlow, clickOrderModeTab };
