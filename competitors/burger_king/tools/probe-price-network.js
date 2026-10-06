'use strict';
/**
 * Live probe: capture network responses that look like BK pricing data
 * while opening the menu for the configured Riyadh branch.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const CONFIG = require('../collector/config');
const priceScraper = require('../collector/price-scraper');
const logger = require('../collector/logger');

logger.init();

const OUT = path.join(__dirname, '../.artifacts/price-network-probe.json');
fs.mkdirSync(path.dirname(OUT), { recursive: true });

function looksLikePricePayload(text) {
  if (!text || text.length < 20) return false;
  const lower = text.toLowerCase();
  if (lower.includes('"prices"') || lower.includes('ispricesloading')) return true;
  if (/sar\s*\d/i.test(text)) return true;
  if (/"amount"\s*:\s*\d/.test(text) && /price|cent|money|currency/i.test(text)) return true;
  if (/"default"\s*:\s*\d/.test(text) && /"min"\s*:\s*\d/.test(text)) return true;
  if (/price\.default|price\.min|"priceCents"|"unitPrice"/i.test(text)) return true;
  // numeric money-looking maps
  if ((text.match(/\b\d+\.\d{2}\b/g) || []).length >= 5 && /menu|product|item|plu/i.test(text)) return true;
  return false;
}

(async () => {
  const hits = [];
  const allUrls = [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    geolocation: { latitude: CONFIG.BRANCH.latitude, longitude: CONFIG.BRANCH.longitude },
    permissions: ['geolocation'],
    viewport: { width: 1440, height: 960 },
    userAgent: CONFIG.STATIC_API_HEADERS['user-agent'],
    locale: 'en-US',
  });
  const page = await context.newPage();

  page.on('response', async (res) => {
    try {
      const url = res.url();
      const status = res.status();
      const ct = (res.headers()['content-type'] || '');
      allUrls.push({ url: url.slice(0, 250), status, ct: ct.slice(0, 80) });
      if (status < 200 || status >= 300) return;
      if (!/json|text|javascript|graphql/i.test(ct) && !/graphql|price|menu|plu|cart|offer/i.test(url)) return;
      let text = '';
      try { text = await res.text(); } catch { return; }
      if (!looksLikePricePayload(text) && !/graphql/i.test(url)) return;
      // Always keep graphql + anything price-like
      const keep = looksLikePricePayload(text) || (/graphql/i.test(url) && /price|amount|cent|plu/i.test(text));
      if (!keep && !/graphql/i.test(url)) return;
      const snippetKeys = [];
      try {
        const j = JSON.parse(text);
        const walk = (o, depth = 0) => {
          if (!o || depth > 4) return;
          if (Array.isArray(o)) { o.slice(0, 5).forEach((x) => walk(x, depth + 1)); return; }
          if (typeof o === 'object') {
            for (const k of Object.keys(o)) {
              if (/price|amount|cent|plu|sar|money|cost/i.test(k)) snippetKeys.push(k);
              if (snippetKeys.length < 40) walk(o[k], depth + 1);
            }
          }
        };
        walk(j);
      } catch {}
      hits.push({
        url: url.slice(0, 400),
        status,
        ct,
        size: text.length,
        priceLike: looksLikePricePayload(text),
        keys: [...new Set(snippetKeys)].slice(0, 30),
        preview: text.slice(0, 500),
      });
    } catch {}
  });

  await page.goto(CONFIG.START_URL, { waitUntil: 'domcontentloaded', timeout: CONFIG.PAGE_TIMEOUT });
  await page.waitForTimeout(4000);
  await priceScraper.acceptCookies(page, logger);
  await priceScraper.openLocationPicker(page, logger);
  const ok = await priceScraper.selectPickupStore(page, logger);
  console.log('store selected', ok, 'url', page.url());
  await page.waitForTimeout(CONFIG.DELAY_BETWEEN_PAGES);
  // scroll menu to trigger lazy price loads
  for (let i = 0; i < 12; i++) {
    await page.mouse.wheel(0, 900);
    await page.waitForTimeout(600);
  }
  await page.waitForTimeout(3000);

  // Also dump any window state if accessible
  let windowProbe = null;
  try {
    windowProbe = await page.evaluate(() => {
      const out = {};
      const candidates = ['__NEXT_DATA__', '__PRELOADED_STATE__', '__INITIAL_STATE__'];
      for (const k of candidates) {
        if (window[k]) out[k] = typeof window[k] === 'object' ? 'object' : typeof window[k];
      }
      // search for prices-looking objects shallowly on window
      const found = [];
      for (const k of Object.keys(window)) {
        try {
          const v = window[k];
          if (v && typeof v === 'object') {
            const s = JSON.stringify(v).slice(0, 2000);
            if (/isPricesLoading|"prices"|price\.default/i.test(s)) found.push(k);
          }
        } catch {}
      }
      out.foundKeys = found.slice(0, 20);
      return out;
    });
  } catch (e) {
    windowProbe = { error: e.message };
  }

  const visible = await priceScraper.extractVisiblePrices(page);
  fs.writeFileSync(OUT, JSON.stringify({
    hits,
    hitCount: hits.length,
    urlCount: allUrls.length,
    graphqlUrls: allUrls.filter((u) => /graphql/i.test(u.url)),
    windowProbe,
    visiblePriceCount: visible.length,
    visibleSample: visible.slice(0, 10),
  }, null, 2));
  console.log('hits', hits.length, 'urls', allUrls.length, 'visiblePrices', visible.length);
  console.log('wrote', OUT);
  for (const h of hits.slice(0, 20)) {
    console.log('-', h.status, h.size, h.keys.slice(0, 10).join(','), h.url.slice(0, 120));
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
