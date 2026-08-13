#!/usr/bin/env node
'use strict';

/**
 * collector/screenshot-capture.js
 * ---------------------------------------------------------------------
 * Playwright screenshot capture - invoked (by backend/run_service.py)
 * ONLY for products the change detector just classified as NEW_PRODUCT
 * (or NEW_OFFER, for "Offers"-category products - see backend/
 * offer_parser.py), never for every product on every run. Mirrors every
 * other competitor's screenshot-capture.js contract exactly.
 *
 * Simpler than Burger King's/KFC's: Herfy's menu page shows the full
 * catalog with no channel/branch selection required at all (see
 * research/api-map/api-map.md - the menu-ref CDN JSON is not
 * branch/channel-scoped), so this module just navigates to the
 * storefront root page once per batch and locates each product by name.
 *
 * Every click still goes through collector/safe-actions.js. This module
 * never fills a payment/OTP field, never clicks "Add to my orders"
 * (أضف إلى طلباتي) or anything cart-related, and never reaches checkout.
 *
 * KNOWN LIMITATION: Herfy's storefront UI is Arabic-first by default (see
 * api-map.md - concept.primary-language is ar-sa), so a product card's
 * visible text may render in Arabic even when this job's `product_name`
 * is the English name read from product_snapshots.product_name_en. This
 * module tries the English name first, then the Arabic name if provided
 * on the job, and otherwise fails the job the same documented,
 * non-blocking way every other competitor's screenshot capture does (see
 * README "Known limitations").
 *
 * Usage:
 *   node collector/screenshot-capture.js --jobs=<path-to-jobs.json> --out=<path-to-results.json>
 *
 * jobs.json: [{ product_id, product_name, product_name_ar, category_name, channel, event_type, date }]
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

async function acceptCookies(page, logger) {
  for (const text of ['Accept', 'Accept All', 'موافق', 'قبول']) {
    const ok = await safe.safeClick(page, `button:has-text("${text}")`, logger, { label: `accept-cookies:${text}` }).catch(() => false);
    if (ok) break;
  }
}

/** Locates the product card by fuzzy visible-text match (tries English, then Arabic name) and returns its element handle, or null. */
async function findProductCard(page, names) {
  for (const name of names.filter(Boolean)) {
    const nameLocator = page.getByText(name, { exact: false }).first();
    if (!(await nameLocator.count().catch(() => 0))) continue;
    const handle = await nameLocator.elementHandle().catch(() => null);
    if (!handle) continue;
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
    if (cardHandle) return cardHandle.asElement();
  }
  return null;
}

async function captureOne(page, job, screenshotDir, logger) {
  const { product_id, product_name, product_name_ar, channel, event_type, date } = job;
  try {
    await safe.scrollGradually(page, 2, 250);
    const card = await findProductCard(page, [product_name, product_name_ar]);
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
      logger.warn(`[SCREENSHOT] Could not locate product card for "${product_name}" / "${product_name_ar}" (id=${product_id}) - saving full-viewport screenshot instead`);
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

  const browser = await chromium.launch({ headless: CONFIG.HEADLESS });
  try {
    const context = await browser.newContext({
      locale: 'en-US',
      viewport: { width: 1440, height: 960 },
      userAgent: CONFIG.STATIC_API_HEADERS['user-agent'],
    });
    context.setDefaultTimeout(CONFIG.ACTION_TIMEOUT);
    const page = await context.newPage();
    let taken = 0;
    try {
      await page.goto(CONFIG.START_URL, { waitUntil: 'networkidle', timeout: CONFIG.PAGE_TIMEOUT });
      await page.waitForTimeout(2000);
      await acceptCookies(page, logger);
      await page.waitForTimeout(1000);

      for (const job of jobs) {
        if (taken >= maxShots) {
          results.push({ product_id: job.product_id, event_type: job.event_type, channel: job.channel, screenshot_path: null, success: false, error: 'MAX_SCREENSHOTS_PER_RUN reached' });
          continue;
        }
        const result = await captureOne(page, job, CONFIG.SCREENSHOTS_DIR, logger);
        results.push(result);
        if (result.success) taken += 1;
        await page.waitForTimeout(CONFIG.DELAY_BETWEEN_ACTIONS);
      }
    } catch (e) {
      logger.error(`[SCREENSHOT] Page setup failed: ${e.message} - recording remaining jobs as failed`);
      for (const job of jobs) {
        if (!results.find((r) => r.product_id === job.product_id && r.event_type === job.event_type)) {
          results.push({ product_id: job.product_id, event_type: job.event_type, channel: job.channel, screenshot_path: null, success: false, error: `page setup failed: ${e.message}` });
        }
      }
    } finally {
      await context.close().catch(() => {});
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
