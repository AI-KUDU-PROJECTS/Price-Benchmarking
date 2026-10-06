# Direct HTTP (no browser) probe transcript

Captured 2026-08-06 using a plain Node `https` client (no Playwright, no
cookie jar) against `saudi.hardees.me`, reproduced formally by
[`../../../tools/probe-public-api.js`](../../../tools/probe-public-api.js). Three
sequential, low-volume requests, ~1.5s apart. No values below are secret -
the deviceid is a locally-generated random string discarded immediately
after this probe, never reused.

## 1. No headers at all

```
POST /api/guestLogin  body: {}
headers: (only content-type/content-length)
```

Result:

```
HTTP 403
server: Microsoft-Azure-Application-Gateway/v2
content-type: text/html
body: <html><head><title>403 Forbidden</title></head>
      <body><center><h1>403 Forbidden</h1></center>
      <hr><center>Microsoft-Azure-Application-Gateway/v2</center></body></html>
```

The WAF blocks the request before it ever reaches the application.

## 2. + browser-shaped headers, no deviceid

```
POST /api/guestLogin  body: {}
headers: + user-agent, origin=https://saudi.hardees.me,
           referer=https://saudi.hardees.me/en/home,
           brand=HRD, country=KSA, language=En, version=v20,
           devicemodel=Chrome, is-dark-mode=0
```

Result:

```
HTTP 500
content-type: application/json
body: {"statusCode":422,"httpCode":422,"type":"DEFAULT_VALIDATION_ERROR",
       "message":"Invalid info provided","attributes":[],
       "heading":{"Ar":"","En":""},"note":{"En":"","Ar":""},"identifier":[]}
```

The WAF now passes the request through (no more HTML 403) - the
*application* itself rejects it. The same happened when this shape was
tried against `getStoreList` with a real payload.

## 3. + a self-generated random deviceid, still no prior cookie jar

```
POST /api/guestLogin  body: {}
headers: same as #2 + deviceid=<32 random hex chars>, refreshtoken=""
```

Result:

```
HTTP 200
set-cookie: t=<guest-session JWT>; ...; HttpOnly; Secure; SameSite=Strict
set-cookie: _t=<refresh-token JWT>; ...; HttpOnly; Secure; SameSite=Strict
body: {"statusCode":200,"httpCode":200,"type":"LOGIN",
       "data":{"brand":"HRD","country":"KSA","isGuest":1, ...,
               "deviceid":"<the same random value we sent>",
               "appbundle":"com.kfc.me","_id":"...","cartId":"..."},
       "message":"Logged In Successfully", ...}
```

A completely fresh guest session was established directly over HTTPS, no
browser involved, using only a self-chosen deviceid value with no
attestation or prior registration.

## Interpretation (see api-map.md "Direct API feasibility")

1. **WAF gate**: `saudi.hardees.me` sits behind the same
   Microsoft-Azure-Application-Gateway/v2 WAF confirmed for
   `saudi.kfc.me` in the KFC investigation - it 403s any request missing
   browser-shaped `user-agent`/`origin`/`referer`, but does not otherwise
   distinguish a real browser from a plain HTTPS client that sends those
   three headers.
2. **deviceid**: required by the application layer on every call, but is
   a plain client-chosen string - no signature, no attestation, no
   server-side pre-registration step was observed.
3. **No cookie jar needed to start**: `guestLogin` can bootstrap a brand
   new session from zero prior state; the response's `Set-Cookie` headers
   are what a client would then need to persist and resend.

This was used only to document the site's own default behavior for its
very first request from any client (exactly what a first-time visitor's
browser already does) - nothing here bypasses CAPTCHA, authentication,
rate limits, or authorization.
