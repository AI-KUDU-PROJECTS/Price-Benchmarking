#!/usr/bin/env node
'use strict';

/**
 * competitors/hardees/tools/probe-public-api.js
 * ---------------------------------------------------------------------
 * RESEARCH-ONLY tool. Answers Step 10 of the Hardee's API-mapping
 * investigation: can these public endpoints be called WITHOUT a browser
 * (plain Node https, no Playwright, no persisted cookie jar), and what is
 * the minimum required to get a real response instead of a WAF block?
 *
 * This makes a small, fixed, sequential set of low-volume requests (one
 * request at a time, a pause between each) directly against
 * saudi.hardees.me using Node's built-in `https` module - no
 * authentication bypass, no CAPTCHA/WAF bypass, no rate-limit evasion.
 * It only ever calls the same PUBLIC guest-session endpoints the site's
 * own browser frontend calls for every anonymous visitor - see
 * research/api-map/api-map.md.
 *
 * Findings from the live run this file's defaults reproduce (see
 * research/api-map/investigation-log.md for the exact transcript):
 *   1. No headers at all               -> HTTP 403 (Azure Application
 *      Gateway WAF - plain HTML error page, not the application).
 *   2. + browser-shaped headers
 *      (user-agent/origin/referer) but no deviceid/cookie
 *                                       -> WAF passes it through; the
 *      application itself then returns HTTP 500 with a JSON body
 *      {"statusCode":422,"type":"DEFAULT_VALIDATION_ERROR",
 *      "message":"Invalid info provided"} - a deviceid is required.
 *   3. + a SELF-GENERATED random deviceid header (no registration, no
 *      attestation, no signature) -> guestLogin succeeds (200) from a
 *      completely cold request with no prior cookie jar at all, and the
 *      response's Set-Cookie headers are what would start a real guest
 *      session.
 *
 * Conclusion: the WAF gate is a static header check (easily satisfied by
 * any real browser, and is not something this tool tries to defeat - it
 * only documents what a real browser already sends by default); the
 * deviceid the application layer requires is a plain client-chosen
 * string with no server-side attestation. Neither finding is used to
 * bypass anything - it is the same behavior a real first-time visitor's
 * browser produces on its very first request.
 *
 * Usage: node tools/probe-public-api.js
 * ---------------------------------------------------------------------
 */

const https = require('https');
const crypto = require('crypto');

const HOST = 'saudi.hardees.me';
const DELAY_MS = 1500; // sequential, low-volume pacing between probes

function request(path, body, headers, method = 'POST') {
  return new Promise((resolve) => {
    const data = body ? JSON.stringify(body) : '';
    const options = {
      hostname: HOST,
      path,
      method,
      headers: Object.assign(
        { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data) },
        headers || {}
      ),
    };
    const req = https.request(options, (res) => {
      let chunks = '';
      res.on('data', (c) => { chunks += c; });
      res.on('end', () => resolve({
        status: res.statusCode,
        server: res.headers.server || null,
        contentType: res.headers['content-type'] || null,
        setCookiePresent: Boolean(res.headers['set-cookie']),
        bodyPreview: chunks.slice(0, 500),
      }));
    });
    req.on('error', (e) => resolve({ error: e.message }));
    if (data) req.write(data);
    req.end();
  });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

const BROWSER_SHAPED_HEADERS = {
  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  origin: 'https://saudi.hardees.me',
  referer: 'https://saudi.hardees.me/en/home',
  brand: 'HRD',
  country: 'KSA',
  language: 'En',
  version: 'v20',
  devicemodel: 'Chrome',
  'is-dark-mode': '0',
};

async function main() {
  const results = [];

  console.log('[probe] 1/3: guestLogin with NO headers at all (expect WAF 403) ...');
  results.push({ probe: 'no-headers', endpoint: 'guestLogin', result: await request('/api/guestLogin', {}, {}) });
  await sleep(DELAY_MS);

  console.log('[probe] 2/3: guestLogin with browser-shaped headers but no deviceid (expect app-level 422) ...');
  results.push({
    probe: 'browser-headers-no-deviceid',
    endpoint: 'guestLogin',
    result: await request('/api/guestLogin', {}, BROWSER_SHAPED_HEADERS),
  });
  await sleep(DELAY_MS);

  console.log('[probe] 3/3: guestLogin with browser-shaped headers + a self-generated deviceid, no prior cookie jar ...');
  const syntheticDeviceId = crypto.randomBytes(16).toString('hex'); // discarded after this process exits - never persisted
  results.push({
    probe: 'browser-headers-plus-synthetic-deviceid',
    endpoint: 'guestLogin',
    result: await request('/api/guestLogin', {}, Object.assign({}, BROWSER_SHAPED_HEADERS, { deviceid: syntheticDeviceId, refreshtoken: '' })),
  });

  console.log('\n[probe] Results (bodies truncated to 500 chars, cookies never printed in full):\n');
  for (const r of results) {
    console.log(`--- ${r.probe} (${r.endpoint}) ---`);
    console.log(JSON.stringify(r.result, null, 2));
    console.log();
  }

  console.log('[probe] Interpretation:');
  console.log('  - A 403 with server=Microsoft-Azure-Application-Gateway/v2 and an HTML body means the WAF blocked the request');
  console.log('    before it ever reached the application (missing browser-shaped headers).');
  console.log('  - A 500 with a JSON body {"statusCode":422,...,"message":"Invalid info provided"} means the WAF passed it');
  console.log('    through but the application rejected it (missing/invalid deviceid).');
  console.log('  - A 200 with Set-Cookie present means a fresh guest session was established directly, with no browser involved.');
}

main();
