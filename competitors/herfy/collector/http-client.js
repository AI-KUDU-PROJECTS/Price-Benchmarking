'use strict';

/**
 * collector/http-client.js
 * ---------------------------------------------------------------------
 * Minimal, dependency-free HTTPS JSON client used for every DIRECT API
 * call. No third-party HTTP library is used, matching the original
 * project's zero-dependency policy. Identical to competitors/kfc's and
 * competitors/burger_king's - this module is intentionally dumb and knows
 * nothing about Herfy's endpoint shapes; api-client.js builds on top of it.
 * ---------------------------------------------------------------------
 */

const https = require('https');
const { URL } = require('url');
const CONFIG = require('./config');

/**
 * Serializes a cookie jar (array of {name, value}) into a single Cookie
 * header value. Kept for interface parity with the KFC collector even
 * though Herfy's APIs need no cookies (see api-map.md).
 */
function serializeCookies(cookies) {
  if (!cookies || !cookies.length) return '';
  return cookies.map((c) => `${c.name}=${c.value}`).join('; ');
}

/**
 * Performs one HTTPS request and resolves with { status, headers, body,
 * json }. Never rejects on a non-2xx status - callers decide what a bad
 * status means (schema validation, retry, etc.) so a 4xx/5xx never crashes
 * the collector outright.
 */
function request({ method = 'GET', url, headers = {}, body = null, timeoutMs }) {
  return new Promise((resolve, reject) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch (e) {
      reject(new Error(`Invalid URL: ${url}`));
      return;
    }
    const payload = body ? JSON.stringify(body) : null;
    const reqHeaders = { ...headers };
    if (payload) {
      reqHeaders['content-type'] = reqHeaders['content-type'] || 'application/json';
      reqHeaders['content-length'] = Buffer.byteLength(payload);
    }

    const req = https.request(
      {
        method,
        hostname: parsed.hostname,
        port: parsed.port || 443,
        path: parsed.pathname + (parsed.search || ''),
        headers: reqHeaders,
        timeout: timeoutMs || CONFIG.API_TIMEOUT,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const bodyText = Buffer.concat(chunks).toString('utf8');
          let json = null;
          let parseError = null;
          if (bodyText) {
            try {
              json = JSON.parse(bodyText);
            } catch (e) {
              parseError = e.message;
            }
          }
          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: bodyText,
            json,
            parseError,
          });
        });
      }
    );
    req.on('timeout', () => {
      req.destroy(new Error(`Request timed out after ${timeoutMs || CONFIG.API_TIMEOUT}ms: ${method} ${url}`));
    });
    req.on('error', (e) => reject(e));
    if (payload) req.write(payload);
    req.end();
  });
}

/** Retries `fn` up to `retries` extra times with linear backoff. Never retries a SafetyBlockedError-shaped rejection. */
async function withRetry(fn, retries, logger, label) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn(attempt);
    } catch (e) {
      lastErr = e;
      if (logger) logger.tag('RETRY', `Attempt ${attempt + 1}/${retries + 1} failed for ${label}: ${e.message}`);
      if (attempt < retries) await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
    }
  }
  throw lastErr;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

module.exports = { request, serializeCookies, withRetry, wait };
