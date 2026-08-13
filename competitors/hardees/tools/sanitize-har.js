#!/usr/bin/env node
'use strict';

/**
 * competitors/hardees/tools/sanitize-har.js
 * ---------------------------------------------------------------------
 * Hardee's-specific adaptation of competitors/kfc/collector/sanitize-har.js
 * (same redaction logic, ported rather than copied by reference so this
 * competitor's tooling stays fully self-contained under
 * competitors/hardees/ - see repo root README.md "Multi-competitor
 * architecture"). Reads any HAR file captured by tools/capture-network.js
 * (or a manual browser-devtools export) and writes a redacted copy next
 * to it. THE ORIGINAL HAR IS NEVER MODIFIED - this always writes to a new
 * "-sanitized" file, and refuses to overwrite the input.
 *
 * Redacted:
 *   - Cookie / Set-Cookie headers and the HAR "cookies" arrays (this is
 *     where Hardee's guest-session JWTs live: the "t"/"_t"/"lat"/"lrt"
 *     cookies observed live - see research/api-map/api-map.md)
 *   - Authorization / bearer / session / CSRF / deviceid headers & values
 *   - Sensitive query-string parameters (token, key, secret, password, ...)
 *   - Card numbers, CVV/CVC, IBAN-shaped values
 *   - Email addresses and phone-number-shaped strings anywhere in a body
 *   - Address-shaped fields (street/building/flat/postal) and precise
 *     lat/long coordinates (Hardee's own validateLocation request bodies
 *     carry raw lat/lng fields directly - see api-map.md)
 *
 * Best-effort, defense-in-depth - not a compliance guarantee. Both the
 * original and the sanitized file should be treated as potentially
 * sensitive until reviewed; only the sanitized file is ever git-tracked
 * (see repo root .gitignore).
 *
 * Usage: node tools/sanitize-har.js <path-to.har> [output-path]
 * ---------------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');

const SENSITIVE_HEADER_NAMES = [
  /cookie/i, /authoriz/i, /\bauth\b/i, /token/i, /session/i, /csrf/i, /xsrf/i,
  /api.?key/i, /secret/i, /credential/i, /\bjwt\b/i, /deviceid/i,
];

const SENSITIVE_PARAM_NAMES = [
  /token/i, /session/i, /auth/i, /key/i, /secret/i, /password/i, /passwd/i,
  /otp/i, /csrf/i, /card/i, /cvv/i, /cvc/i, /iban/i, /credential/i, /\bjwt\b/i,
];

const SENSITIVE_BODY_KEY_NAMES = [
  /token/i, /session/i, /auth/i, /secret/i, /password/i, /passwd/i, /otp/i, /csrf/i,
  /card.?number/i, /cvv/i, /cvc/i, /iban/i, /credential/i, /\bjwt\b/i,
  /phone/i, /mobile/i, /email/i, /street/i, /address/i, /deviceid/i,
  /^lat(itude)?$/i, /latitude/i, /^lon(gitude)?$/i, /longitude/i, /^lng$/i, /coordin/i,
  /building/i, /flat/i, /postal/i, /zip/i, /floor/i,
];

const EMAIL_RE = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
const PHONE_RE = /(?:\+?966[\s-]?)?0?5(?:[\s-]?\d){8}\b|\b\d(?:[\s-]?\d){8,11}\b/g;
const BEARER_RE = /Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi;
const COORD_RE = /-?\d{1,3}\.\d{4,}/g;
const CARD_RE = /\b(?:\d[ -]?){13,19}\b/g;
// Hardee's/AMR-platform session cookies are JWTs (header.payload.signature,
// each base64url) - redact any bare JWT-shaped token even outside a
// recognized cookie/header name, since it decodes to deviceid/sessionId.
const JWT_RE = /eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g;

const REDACTED = '[REDACTED]';

function redactString(value) {
  if (typeof value !== 'string' || !value) return value;
  return value
    .replace(JWT_RE, REDACTED)
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
  const inputPath = process.argv[2];
  if (!inputPath) {
    console.error('[sanitize-har] Usage: node tools/sanitize-har.js <path-to.har-or-api-calls.json> [output-path]');
    process.exit(1);
  }
  const outputPath = process.argv[3] || deriveSanitizedPath(inputPath);

  if (!fs.existsSync(inputPath)) {
    console.error(`[sanitize-har] Input file not found: ${inputPath}`);
    process.exit(1);
  }
  if (path.resolve(inputPath) === path.resolve(outputPath)) {
    console.error('[sanitize-har] Refusing to overwrite the original file. Output path must differ from the input path.');
    process.exit(1);
  }

  console.log(`[sanitize-har] Reading ${inputPath} ...`);
  const raw = fs.readFileSync(inputPath, 'utf8');
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    console.error(`[sanitize-har] Could not parse input as JSON: ${e.message}`);
    process.exit(1);
  }

  let sanitized;
  if (parsed && parsed.log && Array.isArray(parsed.log.entries)) {
    // A real HAR file (from capture-network.js's recordHar, or a manual
    // browser-devtools export).
    console.log(`[sanitize-har] Detected HAR shape. Redacting ${parsed.log.entries.length} entries ...`);
    sanitized = { ...parsed, log: { ...parsed.log, entries: parsed.log.entries.map(redactEntry) } };
  } else if (Array.isArray(parsed)) {
    // capture-network.js's api-calls.json shape: a flat array of
    // {method, path, url, status, requestBody, responseBody}. The bodies
    // themselves carry deviceid/lat/lng values that need the same
    // redaction as a HAR entry's postData/content.
    console.log(`[sanitize-har] Detected api-calls.json shape. Redacting ${parsed.length} call records ...`);
    sanitized = parsed.map((call) => ({
      ...call,
      url: redactUrl(call.url),
      requestBody: typeof call.requestBody === 'string' ? redactBodyText(call.requestBody) : redactJsonValue(call.requestBody),
      responseBody: redactJsonValue(call.responseBody),
    }));
  } else {
    console.error('[sanitize-har] Unrecognized input shape (neither a HAR file nor an api-calls.json array). Refusing to guess.');
    process.exit(1);
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(sanitized));
  console.log(`[sanitize-har] Wrote sanitized copy to ${outputPath}`);
  console.log('[sanitize-har] The original file was left untouched and stays git-ignored (raw/).');
  console.log('[sanitize-har] This pass is best-effort defense-in-depth, not a compliance guarantee - review before sharing.');
}

main();
