"""
competitors/hardees/services/sanitize.py
---------------------------------------------------------------------
Recursive redaction for anything from api/client.py before it is
rendered in the Streamlit UI, logged, or written to disk - see
../research/api-map/api-map.md "Security & sensitive-data notes" and
../tools/sanitize-har.js, whose redaction rules this mirrors in Python
for this live-preview app (a separate implementation, since the HAR
sanitizer works on HAR entries/api-calls.json shapes, not live Python
dicts - the intent and pattern list are the same).

Every real Hardee's API response this project has observed carries no
cookie/token value in its BODY (those live only in headers/cookies, which
this client never surfaces to the UI - see api/client.py's `deviceid`
field being `repr=False`). This module exists as defense-in-depth: if a
future response ever did echo a sensitive-looking field back, it would
still never reach the screen unredacted.
---------------------------------------------------------------------
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_RE = re.compile(
    r"(deviceid|cookie|token|session|authoriz|secret|password|passwd|csrf|xsrf|\bjwt\b|api.?key|credential)",
    re.IGNORECASE,
)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def sanitize(value: Any, _depth: int = 0) -> Any:
    """Returns a redacted deep copy of `value`. Safe on any JSON-shaped
    Python value (dict/list/str/int/float/bool/None); anything else is
    returned as-is. Depth-bounded (like tools/sanitize-har.js) so a
    pathological/cyclic structure can never cause unbounded recursion."""
    if _depth > 25:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                out[key] = REDACTED
            else:
                out[key] = sanitize(val, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in value]
    if isinstance(value, str):
        s = _JWT_RE.sub(REDACTED, value)
        s = _BEARER_RE.sub(f"Bearer {REDACTED}", s)
        s = _EMAIL_RE.sub(REDACTED, s)
        return s
    return value


def error_message(exc: Exception) -> str:
    """A safe, user-facing string for any exception raised by api/client.py
    - never includes headers or the client's deviceid (which isn't part of
    the exception's message/body in the first place - see
    api/client.py's HardeesApiError, which only carries the site's own
    `message`/`type` fields), but still run through sanitize() for
    defense-in-depth before being shown."""
    return sanitize(str(exc))
