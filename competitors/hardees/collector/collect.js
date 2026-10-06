#!/usr/bin/env node
'use strict';

/**
 * collector/collect.js
 * ---------------------------------------------------------------------
 * CLI entry point for the Node half of the collection pipeline. Invoked by
 * backend/run_service.py as a subprocess (per the required Node/Python
 * split: "Node.js: API bootstrap, public API collection, Playwright
 * screenshots / Python: SQLite, change detection, React/BFF, Excel
 * export, scheduler").
 *
 * Usage:
 *   node collector/collect.js --run-id=<id> --channel=PICKUP|DELIVERY|BOTH --out-dir=<dir>
 *
 * Writes, for each requested channel:
 *   <out-dir>/<CHANNEL>.json        - the full channel snapshot (see channel-collector.js)
 *   <out-dir>/raw/<CHANNEL>/*.json  - every raw API request/response pair, for audit
 * and always writes:
 *   <out-dir>/summary.json          - { runId, channels: [...], overallStatus }
 *
 * Exit code is 0 whenever the collector ran to completion, REGARDLESS of
 * whether individual channels report SUCCESS/PARTIAL/FAILED - a channel
 * failure is expected, structured data, not a process crash. Exit code is
 * non-zero only for a genuine unexpected error (bootstrap threw outside
 * all retries, disk write failed, bad arguments).
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');

function loadDotEnvFile(filePath) {
  let content;
  try {
    content = fs.readFileSync(filePath, 'utf8');
  } catch (e) {
    return;
  }
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}
loadDotEnvFile(path.join(__dirname, '..', '..', '..', '.env'));

const CONFIG = require('./config');
const logger = require('./logger');
const { bootstrapSession } = require('./api-bootstrap');
const { collectPickup } = require('./pickup-collector');
const { collectDelivery } = require('./delivery-collector');

function parseArgs(argv) {
  const args = { channel: 'BOTH', runId: null, outDir: null };
  for (const raw of argv.slice(2)) {
    const m = raw.match(/^--([a-z-]+)=(.*)$/i);
    if (!m) continue;
    const key = m[1].toLowerCase();
    const value = m[2];
    if (key === 'channel') args.channel = value.toUpperCase();
    else if (key === 'run-id') args.runId = value;
    else if (key === 'out-dir') args.outDir = value;
  }
  return args;
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

/** A product counts as "having an offer" when it genuinely has a discount/promo, never just because promoId/specialPrice are present as 0/absent placeholders (see api-map.md). */
function isOfferProduct(p) {
  const hasSpecialPrice = p.specialPrice != null && Number(p.specialPrice) > 0 && Number(p.specialPrice) !== Number(p.originalPrice);
  const hasPromoId = p.promoId != null && Number(p.promoId) > 0;
  const isLimited = p.limited_offer === 1 || p.limited_offer === true;
  return hasSpecialPrice || hasPromoId || isLimited;
}

async function runOneChannel(channel, session, outDir) {
  const rawResponses = [];
  const collectFn = channel === 'PICKUP' ? collectPickup : collectDelivery;
  const result = await collectFn(session, logger, {
    onRawResponse: (ch, endpoint, payload, res) => {
      rawResponses.push({ endpoint, payload, status: res && res.status, ok: res && res.ok, data: res && res.data, schema: res && res.schema, capturedAt: new Date().toISOString() });
    },
  });

  // Persist raw endpoint responses for full audit, per spec ("Store
  // raw_api_json ... in organized raw-data files so the original API
  // response is always available for review"). These bodies never contain
  // cookies/tokens (those only ever live in request HEADERS, which are not
  // dumped here), so this is safe to keep on disk (still gitignored).
  const rawDir = path.join(outDir, 'raw', channel);
  fs.mkdirSync(rawDir, { recursive: true });
  for (let i = 0; i < rawResponses.length; i++) {
    const r = rawResponses[i];
    const safeEndpoint = String(r.endpoint).replace(/[^a-z0-9_-]+/gi, '_');
    writeJson(path.join(rawDir, `${String(i).padStart(3, '0')}-${safeEndpoint}.json`), r);
  }

  writeJson(path.join(outDir, `${channel}.json`), result);
  return result;
}

async function main() {
  logger.init();
  const args = parseArgs(process.argv);
  if (!args.runId) {
    console.error('Missing required --run-id=<id>');
    process.exit(2);
  }
  const outDir = args.outDir || path.join(CONFIG.RAW_DIR, args.runId);
  fs.mkdirSync(outDir, { recursive: true });

  const channels = args.channel === 'BOTH' ? ['PICKUP', 'DELIVERY'] : [args.channel];
  for (const c of channels) {
    if (!['PICKUP', 'DELIVERY'].includes(c)) {
      console.error(`Unknown channel: ${c} (expected PICKUP, DELIVERY, or BOTH)`);
      process.exit(2);
    }
  }

  logger.section('COLLECTOR STARTING');
  logger.info(`run_id=${args.runId} channels=${channels.join(',')} branch=${CONFIG.BRANCH.branchName} (storeId=${CONFIG.BRANCH.storeId}) city=${CONFIG.BRANCH.city}`);

  const summary = { runId: args.runId, generatedAt: new Date().toISOString(), branch: CONFIG.BRANCH, channels: [], overallStatus: 'FAILED', bootstrapError: null };

  let session;
  try {
    logger.section('SESSION BOOTSTRAP');
    session = await bootstrapSession(logger);
  } catch (e) {
    logger.error(`[BOOTSTRAP] Fatal: could not establish a session: ${e.message}`);
    summary.bootstrapError = e.message;
    for (const c of channels) {
      summary.channels.push({ channel: c, status: 'FAILED', errorMessage: `Session bootstrap failed: ${e.message}`, categoryCount: 0, productCount: 0, offerCount: 0, expectedCategoryCount: 0, completionPercentage: 0 });
      writeJson(path.join(outDir, `${c}.json`), summary.channels[summary.channels.length - 1]);
    }
    writeJson(path.join(outDir, 'summary.json'), summary);
    logger.close('bootstrap failure');
    process.exit(0); // structured failure, not a crash - see module docstring
    return;
  }

  for (const channel of channels) {
    try {
      const result = await runOneChannel(channel, session, outDir);
      summary.channels.push({
        channel,
        status: result.status,
        errorMessage: result.errorMessage,
        categoryCount: result.categoryCount,
        expectedCategoryCount: result.expectedCategoryCount,
        completionPercentage: result.completionPercentage,
        productCount: result.productCount,
        offerCount: (result.products || []).filter(isOfferProduct).length,
        apiConfigId: result.apiConfigId,
        clusterId: result.clusterId,
        branchCurrentlyClosed: result.branchCurrentlyClosed,
      });
    } catch (e) {
      logger.error(`[RUN] Unexpected error collecting ${channel}: ${e.stack || e.message}`);
      const failed = { channel, status: 'FAILED', errorMessage: `Unexpected error: ${e.message}`, categoryCount: 0, expectedCategoryCount: 0, completionPercentage: 0, productCount: 0, offerCount: 0 };
      summary.channels.push(failed);
      writeJson(path.join(outDir, `${channel}.json`), failed);
    }
    await new Promise((r) => setTimeout(r, CONFIG.DELAY_BETWEEN_PAGES));
  }

  const statuses = summary.channels.map((c) => c.status);
  if (statuses.every((s) => s === 'SUCCESS')) summary.overallStatus = 'SUCCESS';
  else if (statuses.some((s) => s === 'SUCCESS' || s === 'PARTIAL')) summary.overallStatus = 'PARTIAL';
  else summary.overallStatus = 'FAILED';

  writeJson(path.join(outDir, 'summary.json'), summary);
  logger.section(`COLLECTOR FINISHED: overallStatus=${summary.overallStatus}`);
  logger.close('completed');
  process.exit(0);
}

main().catch((e) => {
  console.error('[FATAL]', e.stack || e.message);
  process.exit(1);
});
