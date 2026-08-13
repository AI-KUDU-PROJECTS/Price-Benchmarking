#!/usr/bin/env node
'use strict';

/**
 * collector/sanitize-har.js
 * ---------------------------------------------------------------------
 * Standalone utility, kept from the project's original full-journey HAR
 * crawler (see legacy/). Reads any HAR file and writes a redacted copy
 * next to it - useful if you ever capture a fresh HAR by hand (e.g. via
 * `npx playwright open` or browser devtools) while debugging an API
 * schema change. The ORIGINAL HAR IS NEVER MODIFIED - this always writes
 * to a new "-sanitized" file.
 *
 * Redacted (see README "Sensitive-data warning" for the full rationale):
 *   - Cookie / Set-Cookie headers and the HAR "cookies" arrays
 *   - Authorization / bearer / session / CSRF headers & tokens
 *   - Sensitive query-string parameters (token, key, secret, password, ...)
 *   - Card numbers, CVV/CVC, IBAN-shaped values
 *   - Email addresses and phone-number-shaped strings anywhere in a body
 *   - Address-shaped fields (street/building/flat/postal) and precise
 *     lat/long coordinates
 *
 * This is a best-effort, defense-in-depth pass over JSON/text bodies and
 * headers - it is not a guarantee that zero sensitive data remains, which
 * is exactly why the original HAR is preserved untouched and neither file
 * should be published/shared outside your organization without review.
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');

const DEFAULT_HAR_PATH = path.join(__dirname, '..', 'legacy', 'kfc-saudi-complete-flow.har');

// Header/key/param name patterns below are deliberately UNANCHORED
// (substring, not `^...$` or `\bword\b`) wherever the real-world name could
// plausibly appear as part of a camelCase/kebab-case/PascalCase identifier
// (e.g. "X-CSRFToken", "apikey", "formattedAddress", "flatNumber",
// "zipCode"). A word-boundary anchor requires a non-word character on both
// sides, which fails inside a contiguous run of letters - exactly the gap
// found (and empirically confirmed) during an adversarial review of this
// script. Over-matching here just means an extra value gets redacted,
// which is the safe failure mode for a tool whose entire job is redaction.
const SENSITIVE_HEADER_NAMES = [
  /cookie/i, /authoriz/i, /\bauth\b/i, /token/i, /session/i, /csrf/i, /xsrf/i,
  /api.?key/i, /secret/i, /credential/i, /\bjwt\b/i,
];

const SENSITIVE_PARAM_NAMES = [
  /token/i, /session/i, /auth/i, /key/i, /secret/i, /password/i, /passwd/i,
  /otp/i, /csrf/i, /card/i, /cvv/i, /cvc/i, /iban/i, /credential/i, /\bjwt\b/i,
];

const SENSITIVE_BODY_KEY_NAMES = [
  /token/i, /session/i, /auth/i, /secret/i, /password/i, /passwd/i, /otp/i, /csrf/i,
  /card.?number/i, /cvv/i, /cvc/i, /iban/i, /credential/i, /\bjwt\b/i,
  /phone/i, /mobile/i, /email/i, /street/i, /address/i,
  /^lat(itude)?$/i, /latitude/i, /^lon(gitude)?$/i, /longitude/i, /^lng$/i, /coordin/i,
  /building/i, /flat/i, /postal/i, /zip/i,
];

const EMAIL_RE = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
// Best-effort phone matcher: tolerates optional spaces/dashes between digit
// groups (real-world numbers are rarely typed as one unbroken digit run),
// e.g. "+966 50 123 4567", "050-123-4567", "0501234567".
const PHONE_RE = /(?:\+?966[\s-]?)?0?5(?:[\s-]?\d){8}\b|\b\d(?:[\s-]?\d){8,11}\b/g;
const BEARER_RE = /Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi;
// Decimal coordinates with 4+ decimal places (i.e. precise enough to pinpoint a location).
const COORD_RE = /-?\d{1,3}\.\d{4,}/g;
const CARD_RE = /\b(?:\d[ -]?){13,19}\b/g;

const REDACTED = '[REDACTED]';

function redactString(value) {
  if (typeof value !== 'string' || !value) return value;
  return value
    .replace(BEARER_RE, `Bearer ${REDACTED}`)
    .replace(EMAIL_RE, REDACTED)
    .replace(CARD_RE, REDACTED)
    .replace(COORD_RE, REDACTED)
    .replace(PHONE_RE, REDACTED);
}

function redactHeaderArray(headers) {
  if (!Array.isArray(headers)) return headers;
  return headers.map((h) => {
    if (h && typeof h.name === 'string' && SENSITIVE_HEADER_NAMES.some((re) => re.test(h.name))) {
      return { ...h, value: REDACTED };
    }
    return { ...h, value: redactString(h && h.value) };
  });
}

function redactCookieArray(cookies) {
  if (!Array.isArray(cookies)) return cookies;
  return cookies.map((c) => ({ ...c, value: REDACTED }));
}

function redactQueryString(params) {
  if (!Array.isArray(params)) return params;
  return params.map((p) => {
    if (p && typeof p.name === 'string' && SENSITIVE_PARAM_NAMES.some((re) => re.test(p.name))) {
      return { ...p, value: REDACTED };
    }
    return { ...p, value: redactString(p && p.value) };
  });
}

function redactUrl(rawUrl) {
  try {
    const u = new URL(rawUrl);
    for (const [key] of u.searchParams.entries()) {
      if (SENSITIVE_PARAM_NAMES.some((re) => re.test(key))) {
        u.searchParams.set(key, REDACTED);
      } else {
        const val = u.searchParams.get(key);
        const red = redactString(val);
        if (red !== val) u.searchParams.set(key, red);
      }
    }
    return u.toString();
  } catch (e) {
    return redactString(rawUrl);
  }
}

function redactJsonValue(value, depth = 0) {
  if (depth > 20 || value === null || value === undefined) return value;
  if (typeof value === 'string') return redactString(value);
  if (Array.isArray(value)) return value.map((v) => redactJsonValue(v, depth + 1));
  if (typeof value === 'object') {
    const out = {};
    for (const [key, val] of Object.entries(value)) {
      if (SENSITIVE_BODY_KEY_NAMES.some((re) => re.test(key))) {
        if (Array.isArray(val) && val.every((v) => v === null || typeof v !== 'object')) {
          // Array of primitives under a sensitive key (e.g. GeoJSON-style
          // "coordinates": [lng, lat]) - recursing would only redact
          // string elements and silently leave numeric coordinates
          // untouched, so blank the whole array instead.
          out[key] = REDACTED;
        } else if (Array.isArray(val) || (val && typeof val === 'object')) {
          out[key] = redactJsonValue(val, depth + 1);
        } else {
          out[key] = REDACTED;
        }
      } else {
        out[key] = redactJsonValue(val, depth + 1);
      }
    }
    return out;
  }
  return value;
}

function redactBodyText(text) {
  if (typeof text !== 'string' || !text) return text;
  try {
    const parsed = JSON.parse(text);
    return JSON.stringify(redactJsonValue(parsed));
  } catch (e) {
    return redactString(text);
  }
}

function redactPostData(postData) {
  if (!postData || typeof postData !== 'object') return postData;
  const out = { ...postData };
  if (Array.isArray(out.params)) {
    out.params = out.params.map((p) => {
      if (p && typeof p.name === 'string' && SENSITIVE_BODY_KEY_NAMES.some((re) => re.test(p.name))) {
        return { ...p, value: REDACTED };
      }
      return { ...p, value: redactString(p && p.value) };
    });
  }
  if (typeof out.text === 'string') out.text = redactBodyText(out.text);
  return out;
}

function redactContent(content) {
  if (!content || typeof content !== 'object') return content;
  const out = { ...content };
  if (typeof out.text === 'string') out.text = redactBodyText(out.text);
  return out;
}

function redactEntry(entry) {
  const out = { ...entry };
  if (out.request) {
    out.request = {
      ...out.request,
      url: redactUrl(out.request.url),
      headers: redactHeaderArray(out.request.headers),
      cookies: redactCookieArray(out.request.cookies),
      queryString: redactQueryString(out.request.queryString),
      postData: redactPostData(out.request.postData),
    };
  }
  if (out.response) {
    out.response = {
      ...out.response,
      headers: redactHeaderArray(out.response.headers),
      cookies: redactCookieArray(out.response.cookies),
      content: redactContent(out.response.content),
    };
    if (out.response.redirectURL) out.response.redirectURL = redactUrl(out.response.redirectURL);
  }
  return out;
}

function deriveSanitizedPath(harPath) {
  const dir = path.dirname(harPath);
  const ext = path.extname(harPath) || '.har';
  const base = path.basename(harPath, ext);
  return path.join(dir, `${base}-sanitized${ext}`);
}

function main() {
  const inputPath = process.argv[2] || DEFAULT_HAR_PATH;
  const outputPath = process.argv[3] || deriveSanitizedPath(inputPath);

  if (!fs.existsSync(inputPath)) {
    console.error(`[sanitize-har] Input HAR not found: ${inputPath}`);
    console.error('[sanitize-har] Pass a path explicitly: node collector/sanitize-har.js <path-to.har>');
    process.exit(1);
  }
  if (path.resolve(inputPath) === path.resolve(outputPath)) {
    console.error('[sanitize-har] Refusing to overwrite the original HAR file. Output path must differ from the input path.');
    process.exit(1);
  }

  console.log(`[sanitize-har] Reading ${inputPath} ...`);
  const raw = fs.readFileSync(inputPath, 'utf8');
  let har;
  try {
    har = JSON.parse(raw);
  } catch (e) {
    console.error(`[sanitize-har] Could not parse HAR as JSON: ${e.message}`);
    process.exit(1);
  }

  const entries = (har && har.log && Array.isArray(har.log.entries)) ? har.log.entries : [];
  console.log(`[sanitize-har] Redacting ${entries.length} HAR entries ...`);
  const sanitizedEntries = entries.map(redactEntry);
  const sanitizedHar = { ...har, log: { ...har.log, entries: sanitizedEntries } };

  fs.writeFileSync(outputPath, JSON.stringify(sanitizedHar));
  console.log(`[sanitize-har] Wrote sanitized HAR to ${outputPath}`);
  console.log('[sanitize-har] The original HAR was left untouched. Treat both files as containing session data;');
  console.log('[sanitize-har] this pass is best-effort defense-in-depth, not a compliance guarantee.');
}

main();
