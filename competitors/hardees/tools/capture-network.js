#!/usr/bin/env node
'use strict';

/**
 * competitors/hardees/tools/capture-network.js
 * ---------------------------------------------------------------------
 * RESEARCH-ONLY tool for the Hardee's API-mapping phase. Opens a real
 * Chromium browser (Playwright) against https://saudi.hardees.me/en/home,
 * drives either the Pickup or the Delivery channel-selection flow using
 * safe test coordinates in Riyadh, samples a representative set of menu
 * categories, and records a full HAR + a parallel JSON log of every
 * /api/ request/response pair (method, status, request body, response
 * body) actually observed.
 *
 * This is NOT the future daily collector. It exists only to produce
 * evidence for research/api-map/*. It never logs in, never requests an
 * OTP, never adds a real address, never reaches checkout, and never adds
 * more than one representative item's page to the page's network log per
 * category (no cart mutation of any kind).
 *
 * Usage (from the repository root):
 *   node competitors/hardees/tools/capture-network.js --channel=pickup
 *   node competitors/hardees/tools/capture-network.js --channel=delivery
 *   node competitors/hardees/tools/capture-network.js --channel=pickup --lat=24.70452479 --lng=46.66425169
 *
 * Output (git-ignored - see repo root .gitignore):
 *   competitors/hardees/research/<channel>/raw/<timestamp>/network.har
 *   competitors/hardees/research/<channel>/raw/<timestamp>/api-calls.json
 *   competitors/hardees/research/<channel>/raw/<timestamp>/screenshot.png
 *   competitors/hardees/research/<channel>/raw/<timestamp>/manifest.json
 *
 * Run tools/sanitize-har.js afterwards to produce a git-trackable copy
 * under research/<channel>/sanitized/.
 * ---------------------------------------------------------------------
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..'); // competitors/hardees/
const START_URL = 'https://saudi.hardees.me/en/home';

// Safe, publicly-known test coordinates in Riyadh - NOT a real personal
// address. DEFAULT_PICKUP_COORDS matches a real Hardee's branch's own
// published location (EUROMARCHE-H, storeId=24, from a live getStoreList
// response) so the Self-Pickup "Use my Location" flow deterministically
// resolves to a stable, known branch. DEFAULT_DELIVERY_COORDS is a
// generic central-Riyadh point used only to exercise validateLocation.
const DEFAULT_PICKUP_COORDS = { lat: 24.70452479, lng: 46.66425169 };
const DEFAULT_DELIVERY_COORDS = { lat: 24.7136, lng: 46.6753 };

// Representative categories sampled every run, covering: a burger, a
// meal/box, a side/drink, and two offer/deal categories - discovered live
// from a real getMenu response (see research/api-map/investigation-log.md).
const SAMPLE_CATEGORY_IDS = ['666', '667', '664', '669', '670', '1480', '662'];

// Last known-good getMenuConfig result observed live on 2026-08-06 (see
// research/api-map/api-map.md) - used ONLY as a fallback if this run's own
// getMenuConfig call cannot be found in time; the sampling step always
// prefers whatever this session's OWN getMenuConfig call actually returned.
const FALLBACK_CLUSTER = { cluster: '1_8', configId: 'HRD_SA_23' };

function parseArgs() {
  const args = { channel: 'pickup' };
  for (const raw of process.argv.slice(2)) {
    const m = raw.match(/^--([^=]+)=(.*)$/);
    if (m) args[m[1]] = m[2];
  }
  return args;
}

function timestamp() {
  // Deliberately NOT Date.now() convenience - this is a real wall-clock
  // stamp for a folder name, fine here (unlike the Workflow tool's script
  // sandbox, this is a plain Node CLI script).
  return new Date().toISOString().replace(/[:.]/g, '-');
}

async function main() {
  const args = parseArgs();
  const channel = (args.channel || 'pickup').toLowerCase();
  if (!['pickup', 'delivery'].includes(channel)) {
    console.error(`[capture-network] --channel must be "pickup" or "delivery", got: ${channel}`);
    process.exit(1);
  }
  const defaults = channel === 'pickup' ? DEFAULT_PICKUP_COORDS : DEFAULT_DELIVERY_COORDS;
  const coords = {
    latitude: parseFloat(args.lat || defaults.lat),
    longitude: parseFloat(args.lng || defaults.lng),
  };

  const outDir = path.join(ROOT, 'research', channel, 'raw', timestamp());
  fs.mkdirSync(outDir, { recursive: true });
  console.log(`[capture-network] channel=${channel} coords=${JSON.stringify(coords)} outDir=${outDir}`);

  const log = [];
  const step = async (name, fn) => {
    console.log(`[capture-network] step: ${name}`);
    try { await fn(); log.push({ name, ok: true }); }
    catch (e) { log.push({ name, ok: false, error: e.message }); console.log(`[capture-network]   -> failed: ${e.message.split('\n')[0]}`); }
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    locale: 'en-US',
    geolocation: coords,
    permissions: ['geolocation'],
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    // "omit": the HAR keeps every request/response's URL, headers, status,
    // and timing, but not embedded bodies - the actual /api/ request and
    // response JSON bodies (the evidence that matters) are captured in
    // full separately, in api-calls.json below. Embedding bodies for every
    // request including binary map-tile/font assets from the Delivery
    // flow's Google Maps widget produced 15-25MB HAR files for no benefit
    // (nothing in api-map.md reads a map tile).
    recordHar: { path: path.join(outDir, 'network.har'), content: 'omit' },
  });
  // Block everything that isn't the Hardee's site itself or its own CDN
  // assets. This keeps the HAR focused on Hardee's traffic (the only
  // traffic in scope for this investigation), and makes runs fast and
  // deterministic instead of depending on third-party ad/analytics
  // endpoints that are irrelevant here and were observed to be slow.
  await context.route('**/*', (route) => {
    const url = route.request().url();
    // hardees.me/americanarest.com/blob storage: the app itself and its
    // CDN assets. googleapis.com/gstatic.com: the Delivery flow's map
    // widget (Google Maps) is a genuine, first-party-configured
    // dependency of the site (see its own CSP header), not ad/analytics
    // noise, and the "Select Delivery Location" modal cannot resolve a
    // pin without it.
    if (/(^https:\/\/[^/]*\.?hardees\.me\/)|(^https:\/\/[^/]*\.?americanarest\.com\/)|(^https:\/\/[^/]*\.blob\.core\.windows\.net\/)|(^https:\/\/[^/]*\.googleapis\.com\/)|(^https:\/\/[^/]*\.gstatic\.com\/)/i.test(url)) {
      return route.continue();
    }
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on('console', (msg) => { if (msg.type() === 'error') log.push({ name: 'console-error', text: msg.text().slice(0, 300) }); });

  const apiCalls = [];
  page.on('response', async (res) => {
    const url = res.url();
    if (!url.includes('saudi.hardees.me/api/')) return;
    const req = res.request();
    let requestBody = null;
    try { requestBody = req.postData(); } catch (e) { /* no body */ }
    let responseBody = null;
    try {
      const ct = res.headers()['content-type'] || '';
      responseBody = ct.includes('json') ? await res.json() : await res.text();
    } catch (e) {
      responseBody = `<could not read body: ${e.message}>`;
    }
    apiCalls.push({
      ts: apiCalls.length,
      method: req.method(),
      path: url.split('/api/')[1],
      url,
      status: res.status(),
      requestBody,
      responseBody,
    });
  });

  await step('goto-home', async () => {
    await page.goto(START_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(3000);
  });
  await step('dismiss-cookie-banner', async () => {
    await page.getByText('Got It', { exact: true }).first().click({ timeout: 5000 });
  });
  await page.waitForTimeout(1000);

  let resolvedStore = null;
  if (channel === 'pickup') {
    await step('open-self-pickup-modal', async () => {
      await page.getByText('Self-Pickup', { exact: true }).first().click();
      await page.waitForTimeout(1200);
    });
    await step('use-my-location', async () => {
      // .catch() attached immediately: if the click below throws, this
      // promise must still have a handler or its later rejection (e.g.
      // once the browser closes at the end of the run) becomes an
      // unhandled rejection that crashes the whole Node process.
      const wait = page.waitForResponse((r) => r.url().includes('/api/getNewStore'), { timeout: 15000 }).catch(() => null);
      await page.getByText('Use my Location', { exact: true }).first().click();
      const resp = await wait;
      resolvedStore = resp ? await resp.json().catch(() => null) : null;
    });
    await step('proceed', async () => {
      const btn = page.getByRole('button', { name: 'Proceed' });
      await btn.waitFor({ state: 'visible', timeout: 5000 });
      for (let i = 0; i < 20; i++) {
        if (!(await btn.isDisabled().catch(() => true))) break;
        await page.waitForTimeout(500);
      }
      await btn.click({ timeout: 5000 });
      await page.waitForTimeout(2000);
    });
  } else {
    await step('open-delivery-address-modal', async () => {
      await page.getByText('SELECT LOCATION').first().click();
      await page.waitForTimeout(2000);
    });
    await step('confirm-location', async () => {
      // Deliberately stops here: validateLocation's own response already
      // carries the full resolved store object (see api-map.md). We never
      // proceed to fill in street/building/floor/flat or click Continue -
      // that would create/save an address, which is out of scope and
      // unnecessary for API mapping.
      const wait = page.waitForResponse((r) => r.url().includes('/api/validateLocation'), { timeout: 15000 }).catch(() => null);
      await page.getByRole('button', { name: 'CONFIRM LOCATION' }).click({ timeout: 8000 });
      const resp = await wait;
      resolvedStore = resp ? await resp.json().catch(() => null) : null;
    });
  }

  // Sample representative categories directly (same-origin in-page fetch,
  // reusing the real session this browser just established) rather than
  // fighting a lazily-virtualized product grid's click targets - see
  // research/api-map/investigation-log.md for why.
  await step('sample-categories', async () => {
    // Prefer a getMenuConfig call this session already made (captured by
    // the page.on('response') listener above) over waiting for a new one,
    // since the channel-selection steps already triggered it at least
    // once; only fall back to FALLBACK_CLUSTER if none was ever seen.
    const seen = apiCalls.find((c) => c.path && c.path.startsWith('getMenuConfig') && c.responseBody && c.responseBody.data && c.responseBody.data.menuConfigId);
    const cluster = seen ? seen.responseBody.data.clusterId : FALLBACK_CLUSTER.cluster;
    const configId = seen ? seen.responseBody.data.menuConfigId : FALLBACK_CLUSTER.configId;
    const deviceid = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('profileDraft') || '{}').deviceid || ''; } catch (e) { return ''; }
    }).catch(() => '');
    for (const id of SAMPLE_CATEGORY_IDS) {
      await page.evaluate(async ({ id, cluster, configId, deviceid }) => {
        await fetch('/api/getProductsByCategory', {
          method: 'POST',
          headers: {
            'content-type': 'application/json', brand: 'HRD', country: 'KSA', language: 'En',
            version: 'v20', devicemodel: 'Chrome', 'is-dark-mode': '0', deviceid, refreshtoken: '',
          },
          body: JSON.stringify({ cluster, id, Language: 'En', configId }),
        }).catch(() => {});
      }, { id, cluster, configId, deviceid });
      await page.waitForTimeout(800); // sequential, low-volume pacing
    }
  });

  await page.screenshot({ path: path.join(outDir, 'screenshot.png'), fullPage: true }).catch(() => {});

  fs.writeFileSync(path.join(outDir, 'api-calls.json'), JSON.stringify(apiCalls, null, 2));
  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify({
    channel, coords, resolvedStore, sampledCategoryIds: SAMPLE_CATEGORY_IDS,
    capturedAt: timestamp(), stepLog: log, apiCallCount: apiCalls.length,
  }, null, 2));

  await context.close(); // REQUIRED for recordHar to flush to disk - browser.close() alone does not.
  await browser.close();

  console.log(`[capture-network] done. ${apiCalls.length} /api/ calls captured.`);
  console.log(`[capture-network] resolvedStore: ${JSON.stringify(resolvedStore && resolvedStore.data)}`);
  console.log(`[capture-network] Next: node tools/sanitize-har.js "${path.join(outDir, 'network.har')}"`);
}

main().catch((e) => {
  console.error('[capture-network] fatal error:', e);
  process.exit(1);
});
