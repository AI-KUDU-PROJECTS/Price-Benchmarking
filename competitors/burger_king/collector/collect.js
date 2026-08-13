#!/usr/bin/env node
'use strict';

/**
 * collector/collect.js
 * ---------------------------------------------------------------------
 * CLI entry point for the Node half of the collection pipeline. Invoked
 * by backend/run_service.py as a subprocess, mirroring
 * competitors/kfc/collector/collect.js's contract exactly so the Python
 * backend can ingest either brand's output identically.
 *
 * Usage:
 *   node collector/collect.js --run-id=<id> --channel=PICKUP|DELIVERY|BOTH --out-dir=<dir>
 *
 * Writes, for each requested channel:
 *   <out-dir>/<CHANNEL>.json        - the full channel snapshot (see channel-collector.js)
 *   <out-dir>/raw/<CHANNEL>/*.json  - every raw API request/response pair, for audit
 * and always writes:
 *   <out-dir>/summary.json          - { runId, branch, channels: [...], overallStatus }
 *
 * Unlike KFC, there is no session-bootstrap step here - Burger King's
 * GraphQL endpoints need no cookies/auth at all (see
 * research/api-map/api-map.md), so collection starts directly with the
 * branch-verification call. Exit code is 0 whenever the collector ran to
 * completion, regardless of individual channel SUCCESS/PARTIAL/FAILED -
 * a channel failure is expected, structured data, not a process crash.
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
loadDotEnvFile(path.join(__dirname, '..', '..', '..', '.env')); // repo root .env - see README "Configuration"

const CONFIG = require('./config');
const logger = require('./logger');
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

/** A product counts as "having an offer" only when it genuinely has a discount/promo signal - see backend/offer_parser.py (kept in sync manually, not shared code, same as KFC). */
function isOfferProduct(p) {
  const hasSpecialPrice = false; // Burger King's GetMenuSections carries no price field at all (see api-map.md) - special-price detection happens Python-side once a real pricing signal is confirmed; this Node-side summary count is best-effort only.
  const hasPromoId = false;
  const isLimited = false;
  return hasSpecialPrice || hasPromoId || isLimited;
}

async function runOneChannel(channel, outDir) {
  const rawResponses = [];
  const collectFn = channel === 'PICKUP' ? collectPickup : collectDelivery;
  const result = await collectFn(logger, {
    onRawResponse: (endpoint, res) => {
      if (!res) return;
      rawResponses.push({ endpoint, status: res.status, ok: res.ok, data: res.data, schema: res.schema, capturedAt: new Date().toISOString() });
    },
  });

  // Persist raw endpoint responses for full audit. These never contain
  // cookies/tokens (Burger King's APIs need none - see api-map.md "What
  // is never recorded here"), so this is safe to keep on disk (still
  // gitignored, matching every other competitor's data/raw/ handling).
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

  for (const channel of channels) {
    try {
      logger.section(`CHANNEL: ${channel}`);
      const result = await runOneChannel(channel, outDir);
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
      logger.tag('CHANNEL', `${channel} finished: status=${result.status} products=${result.productCount} categories=${result.categoryCount}`);
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
