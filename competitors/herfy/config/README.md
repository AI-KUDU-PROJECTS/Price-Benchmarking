# competitors/herfy/config/

Reserved for future non-Python declarative configuration (e.g. a
per-competitor `.env` once configuration is no longer shared at the repo
root - see root README.md).

Herfy's actual runtime configuration lives in:

- [`../backend/config.py`](../backend/config.py) (Python side)
- [`../collector/config.js`](../collector/config.js) (Node side)

Both currently read the shared `.env` at the repository root.
