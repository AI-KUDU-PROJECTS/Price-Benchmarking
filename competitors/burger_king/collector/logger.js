'use strict';

/**
 * collector/logger.js
 * Minimal, dependency-free logger shared by every collector/* module.
 * Writes every line to stdout AND appends it to data/logs/collector.log,
 * so a run's full history survives even if the parent Python process only
 * captures stdout in a summary. Call init() once at startup before
 * anything else logs. Identical to competitors/kfc's logger.js.
 */

const fs = require('fs');
const path = require('path');
const CONFIG = require('./config');

const LOG_DIR = path.join(CONFIG.DATA_DIR, 'logs');
const LOG_FILE = path.join(LOG_DIR, 'collector.log');

let logStream = null;
let initialized = false;

function ensureDirs() {
  for (const dir of [CONFIG.DATA_DIR, CONFIG.RAW_DIR, CONFIG.SCREENSHOTS_DIR, CONFIG.ARTIFACTS_DIR, LOG_DIR]) {
    try {
      fs.mkdirSync(dir, { recursive: true });
    } catch (e) {
      // non-fatal: writes into that dir will just fail later and be logged then
    }
  }
}

function init() {
  if (initialized) return;
  ensureDirs();
  try {
    logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });
  } catch (e) {
    logStream = null;
    console.error('[logger] Could not open collector.log for writing:', e.message);
  }
  initialized = true;
  write('SESSION', `=== Collector session started ${new Date().toISOString()} ===`);
}

function write(tag, message) {
  const line = `[${new Date().toISOString()}] [${tag}] ${message}`;
  console.log(line);
  if (logStream) {
    try {
      logStream.write(line + '\n');
    } catch (e) {
      // swallow: logging must never crash the collector
    }
  }
}

function close(reason) {
  if (reason) write('SESSION', `=== Collector session ending: ${reason} ===`);
  if (logStream) {
    try { logStream.end(); } catch (e) { /* ignore */ }
  }
}

module.exports = {
  init,
  close,
  log: write,
  tag: write,
  info: (msg) => write('INFO', msg),
  warn: (msg) => write('WARN', msg),
  error: (msg) => write('ERROR', msg),
  success: (msg) => write('OK', msg),
  section: (msg) => write('SECTION', `--- ${msg} ---`),
  debug: (msg) => write('DEBUG', msg),
};
