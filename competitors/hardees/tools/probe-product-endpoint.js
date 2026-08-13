#!/usr/bin/env node
'use strict';

/**
 * competitors/hardees/tools/probe-product-endpoint.js
 * ---------------------------------------------------------------------
 * RESEARCH-ONLY tool. Formalizes the resolved request format for
 * POST /api/product and POST /api/product-bundle-step (see
 * research/api-map/unresolved-items.md item #1's resolution and
 * research/api-map/api-map.md's endpoint entries for both). Both were
 * originally guessed with only {id, cluster, menuConfigId} and rejected
 * (422 / empty data) - the missing fields, discovered by driving a REAL
 * "Customize" click in a real browser and inspecting the request it
 * actually sent, are `categoryId` and `service`.
 *
 * This tool bootstraps a guest session with Playwright (same pattern as
 * capture-network.js), then makes the two calls via a same-origin
 * fetch() from inside the page - no cart mutation, no "Add to cart"
 * click, nothing beyond these two read-only detail lookups.
 *
 * Usage (from the repository root):
 *   node competitors/hardees/tools/probe-product-endpoint.js --id=9074 --categoryId=666
 *   node competitors/hardees/tools/probe-product-endpoint.js --id=12187 --categoryId=664 --service=PICKUP
 *
 * For a 'bundle_group' wrapper product (see api-map.md "Product and
 * offer response shapes"), pass the WRAPPER's own `selectedItem` field
 * value as --id, not the wrapper's own id - e.g. for "Roast Beef Box"
 * (wrapper id 77772960, selectedItem 12187), use --id=12187. Passing the
 * wrapper's own id returns an empty data:{} - this is intentional
 * platform behavior (nested item identity), not an error in this tool.
 *
 * Output: prints the two responses' key fields to stdout and writes the
 * full result to the --out path if given (defaults to not writing a
 * file at all, so a quick ad-hoc check leaves nothing behind).
 * ---------------------------------------------------------------------
 */

const { chromium } = require('playwright');
const fs = require('fs');

function parseArgs() {
  const args = {};
  for (const raw of process.argv.slice(2)) {
    const m = raw.match(/^--([^=]+)=(.*)$/);
    if (m) args[m[1]] = m[2];
  }
  return args;
}

async function main() {
  const args = parseArgs();
  if (!args.id || !args.categoryId) {
    console.error('[probe-product-endpoint] Usage: --id=<productId> --categoryId=<categoryId> [--cluster=1_8] [--menuConfigId=HRD_SA_23] [--service=PICKUP|DELIVERY] [--out=<path>]');
    process.exit(1);
  }
  const cluster = args.cluster || '1_8';
  const menuConfigId = args.menuConfigId || 'HRD_SA_23';
  const service = args.service || 'DELIVERY'; // matches the site's own observed default when no channel has been explicitly selected - see api-map.md
  const productId = parseInt(args.id, 10);
  const categoryId = parseInt(args.categoryId, 10);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    locale: 'en-US',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  });
  const page = await context.newPage();

  await page.goto('https://saudi.hardees.me/en/home', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(4000);

  const deviceid = await page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('profileDraft') || '{}').deviceid || ''; } catch (e) { return ''; }
  }).catch(() => '');

  const headers = {
    'content-type': 'application/json', brand: 'HRD', country: 'KSA', language: 'En',
    version: 'v20', devicemodel: 'Chrome', 'is-dark-mode': '0', deviceid, refreshtoken: '',
  };

  async function call(path, body) {
    return page.evaluate(async ({ path, body, headers }) => {
      const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });
      let json = null;
      try { json = await res.json(); } catch (e) { /* non-JSON body */ }
      return { status: res.status, body: json };
    }, { path, body, headers });
  }

  const productBody = { id: productId, cluster, categoryId, service, Language: 'En', menuConfigId };
  const product = await call('/api/product', productBody);
  await page.waitForTimeout(800); // low-volume pacing between the two calls
  const bundleStepBody = { id: productId, cluster, categoryId, service, Language: 'En', menuConfigId, stepId: 1 };
  const bundleStep = await call('/api/product-bundle-step', bundleStepBody);

  await browser.close();

  const result = { productBody, product, bundleStepBody, bundleStep };
  console.log('=== POST /api/product ===');
  console.log('request:', JSON.stringify(productBody));
  console.log('status:', product.status);
  if (product.body && product.body.data) {
    const d = product.body.data;
    console.log('name:', d.name, '| originalPrice:', d.originalPrice, '| specialPrice:', d.specialPrice, '| promoId:', d.promoId);
    console.log('steps:', (d.steps || []).map((s) => `${s.title} (${(s.options || []).length} options)`).join('; '));
    console.log('variants:', (d.variants || []).map((v) => `${v.title}: ${(v.options || []).map((o) => o.title).join('/')}`).join('; '));
  } else {
    console.log('(no data - see api-map.md "Product and offer response shapes" for the nested-item-id note if this was a bundle_group wrapper id)');
  }
  console.log();
  console.log('=== POST /api/product-bundle-step ===');
  console.log('request:', JSON.stringify(bundleStepBody));
  console.log('status:', bundleStep.status);
  if (Array.isArray(bundleStep.body && bundleStep.body.data)) {
    console.log('steps returned:', bundleStep.body.data.map((s) => `${s.title} (${(s.options || []).length} options)`).join('; '));
  } else {
    console.log('response:', JSON.stringify(bundleStep.body).slice(0, 300));
  }

  if (args.out) {
    fs.writeFileSync(args.out, JSON.stringify(result, null, 2));
    console.log(`\nWrote full result to ${args.out}`);
  }
}

main().catch((e) => {
  console.error('[probe-product-endpoint] fatal error:', e);
  process.exit(1);
});
