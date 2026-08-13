#!/usr/bin/env node
'use strict';

/**
 * collector/screenshot-capture.js
 * ---------------------------------------------------------------------
 * Playwright screenshot capture - invoked (by backend/run_service.py)
 * ONLY for products/offers the change detector just classified as
 * NEW_PRODUCT or NEW_OFFER, never for every product on every run.
 * Mirrors competitors/kfc/collector/screenshot-capture.js's contract
 * exactly. Reuses the exact navigation steps already verified in
 * price-scraper.js (cookie accept, location picker, pickup/delivery
 * store selection) rather than duplicating them.
 *
 * Every click still goes through collector/safe-actions.js - this module
 * can only ever navigate + click a channel/store selector + a category
 * link + screenshot; it never fills a payment/OTP field, never adds to
 * cart, never reaches checkout.
 *
 * Usage:
 *   node collector/screenshot-capture.js --jobs=<path-to-jobs.json> --out=<path-to-results.json>
 *
 * jobs.json: [{ product_id, product_name, category_name, channel, event_type, date }]
 * results.json (always written, one entry per job, in the same order):
 *   [{ product_id, event_type, channel, screenshot_path|null, success, error|null }]
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const CONFIG = require('./config');
const logger = require('./logger');
const safe = require('./safe-actions');
const priceScraper = require('./price-scraper');

function parseArgs(argv) {
  const args = {};
  for (const raw of argv.slice(2)) {
    const m = raw.match(/^--([a-z-]+)=(.*)$/i);
    if (m) args[m[1]] = m[2];
  }
  return args;
}

function sanitizeForFilename(text) {
  return String(text || '').replace(/[^a-z0-9_-]+/gi, '_').slice(0, 60);
}

/** Gets a page to /en/menu with the given channel's store already selected. */
async function selectChannelAndReachMenu(page, channel, logger) {
  await page.goto(CONFIG.START_URL, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT });
  await page.waitForTimeout(4000);
  await priceScraper.acceptCookies(page, logger);
  await priceScraper.openLocationPicker(page, logger);

  const selected = channel === 'PICKUP' ? await priceScraper.selectPickupStore(page, logger) : await priceScraper.selectDeliveryAddress(page, logger);
  if (!selected) return false;
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
  return /\/en\/menu/.test(page.url());
}

/** Tries to click the named category link; returns true if found and clicked. */
async function openCategory(page, categoryName, logger) {
  if (!categoryName) return false;
  const tab = page.getByText(new RegExp(`^${categoryName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'i')).first();
  if (!(await tab.count().catch(() => 0))) return false;
  const clicked = await safe.safeClick(page, tab, logger, { label: `category:${categoryName}` }).catch(() => false);
  if (clicked) await page.waitForTimeout(2000);
  return !!clicked;
}

/** Locates the product/offer card by fuzzy visible-text match and returns its element handle, or null. */
async function findProductCard(page, productName) {
  const nameLocator = page.getByText(productName, { exact: false }).first();
  if (!(await nameLocator.count().catch(() => 0))) return null;
  const handle = await nameLocator.elementHandle().catch(() => null);
  if (!handle) return null;
  const cardHandle = await handle
    .evaluateHandle((el) => {
      let node = el;
      for (let i = 0; i < 6 && node.parentElement; i++) {
        node = node.parentElement;
        const rect = node.getBoundingClientRect();
        if (rect.width > 100 && rect.height > 100 && rect.width < 700) return node;
      }
      return node;
    })
    .catch(() => null);
  return cardHandle ? cardHandle.asElement() : null;
}

async function captureOne(page, job, screenshotDir, logger) {
  const { product_id, product_name, category_name, channel, event_type, date } = job;
  try {
    if (category_name) await openCategory(page, category_name, logger);
    await safe.scrollGradually(page, 2, 250);
    const card = await findProductCard(page, product_name);
    const dateDir = path.join(screenshotDir, date || new Date().toISOString().slice(0, 10), channel);
    fs.mkdirSync(dateDir, { recursive: true });
    const filename = `${sanitizeForFilename(product_id)}_${event_type}_${Date.now()}.png`;
    const outPath = path.join(dateDir, filename);

    if (card) {
      await card.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(300);
      await card.screenshot({ path: outPath }).catch(async () => {
        await page.screenshot({ path: outPath, fullPage: false });
      });
    } else {
      logger.warn(`[SCREENSHOT] Could not locate product card for "${product_name}" (id=${product_id}) - saving full-viewport screenshot instead`);
      await page.screenshot({ path: outPath, fullPage: false });
    }
    logger.success(`[SCREENSHOT] Captured ${event_type} for "${product_name}" -> ${outPath}`);
    return { product_id, event_type, channel, screenshot_path: outPath, success: true, error: null };
  } catch (e) {
    logger.warn(`[SCREENSHOT] Failed to capture "${product_name}" (id=${product_id}): ${e.message}`);
    return { product_id, event_type, channel, screenshot_path: null, success: false, error: e.message };
  }
}

async function main() {
  logger.init();
  const args = parseArgs(process.argv);
  if (!args.jobs || !args.out) {
    console.error('Usage: node collector/screenshot-capture.js --jobs=<jobs.json> --out=<results.json>');
    process.exit(2);
  }
  const jobs = JSON.parse(fs.readFileSync(args.jobs, 'utf8'));
  const results = [];
  const maxShots = CONFIG.MAX_SCREENSHOTS_PER_RUN;

  if (!jobs.length) {
    fs.writeFileSync(args.out, JSON.stringify([], null, 2));
    logger.info('[SCREENSHOT] No jobs to capture - exiting');
    return;
  }

  logger.section('SCREENSHOT CAPTURE');
  logger.info(`${jobs.length} job(s) requested, cap=${maxShots}`);

  const byChannel = new Map();
  for (const job of jobs) {
    if (!byChannel.has(job.channel)) byChannel.set(job.channel, []);
    byChannel.get(job.channel).push(job);
  }

  let taken = 0;
  const browser = await chromium.launch({ headless: CONFIG.HEADLESS });
  try {
    for (const [channel, channelJobs] of byChannel.entries()) {
      if (taken >= maxShots) {
        for (const job of channelJobs) results.push({ product_id: job.product_id, event_type: job.event_type, channel, screenshot_path: null, success: false, error: 'MAX_SCREENSHOTS_PER_RUN reached' });
        continue;
      }
      const context = await browser.newContext({
        geolocation: { latitude: CONFIG.BRANCH.latitude, longitude: CONFIG.BRANCH.longitude },
        permissions: ['geolocation'],
        locale: 'en-US',
        viewport: { width: 1440, height: 960 },
        userAgent: CONFIG.STATIC_API_HEADERS['user-agent'],
      });
      context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
      const page = await context.newPage();
      try {
        const reachedMenu = await selectChannelAndReachMenu(page, channel, logger);
        if (!reachedMenu) throw new Error('could not reach the menu page for this channel');

        for (const job of channelJobs) {
          if (taken >= maxShots) {
            results.push({ product_id: job.product_id, event_type: job.event_type, channel, screenshot_path: null, success: false, error: 'MAX_SCREENSHOTS_PER_RUN reached' });
            continue;
          }
          const result = await captureOne(page, job, CONFIG.SCREENSHOTS_DIR, logger);
          results.push(result);
          if (result.success) taken += 1;
          await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
        }
      } catch (e) {
        logger.error(`[SCREENSHOT] Channel ${channel} setup failed: ${e.message} - recording remaining jobs as failed`);
        for (const job of channelJobs) {
          if (!results.find((r) => r.product_id === job.product_id && r.event_type === job.event_type)) {
            results.push({ product_id: job.product_id, event_type: job.event_type, channel, screenshot_path: null, success: false, error: `channel setup failed: ${e.message}` });
          }
        }
      } finally {
        await context.close().catch(() => {});
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }

  fs.mkdirSync(path.dirname(args.out), { recursive: true });
  fs.writeFileSync(args.out, JSON.stringify(results, null, 2));
  logger.section(`SCREENSHOT CAPTURE FINISHED: ${results.filter((r) => r.success).length}/${results.length} succeeded`);
  logger.close('completed');
}

main().catch((e) => {
  console.error('[FATAL]', e.stack || e.message);
  process.exit(1);
});
