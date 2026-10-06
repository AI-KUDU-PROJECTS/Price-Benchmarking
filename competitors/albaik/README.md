# Albaik Price Intelligence

**Status: Scaffold only.** No collector, API research, database, change
detection, or dashboard logic exists yet for Albaik. This folder only
holds the isolated structure future implementation will fill in - see
root [README.md](../../README.md) for the multi-competitor architecture.

## Status of every competitor in this repo

```text
KFC:          Implemented
Hardee's:     Scaffold only
McDonald's:   Scaffold only
Burger King:  Scaffold only
Herfy:        Scaffold only
Albaik:       Scaffold only
```

## What exists here today

```
competitors/albaik/
├── README.md            This file
├── __init__.py
├── config/__init__.py    Empty - no configuration values yet
├── collector/README.md   Empty - will hold Node.js API bootstrap + collection code (see below)
├── backend/__init__.py   Empty - no storage/change-detection code yet
├── dashboard/
│   ├── __init__.py
│   └── page.py           render() shows only a status placeholder - no product data
├── research/
│   ├── pickup/           Empty - future Pickup-channel HAR captures / notes go here
│   ├── delivery/         Empty - future Delivery-channel HAR captures / notes go here
│   └── api-map/          Empty - future api-map.json / api-map.md go here
├── data/
│   ├── raw/              Empty - future raw API JSON dumps
│   ├── screenshots/      Empty - future NEW_PRODUCT/NEW_OFFER screenshots
│   ├── logs/              Empty - future collector logs
│   └── database/          Empty - future albaik_monitor.db lives here, isolated from every other competitor
├── exports/                Empty - future Excel exports
└── tests/__init__.py       Empty - no tests yet (nothing to test)
```

Every directory above is empty except for a `.gitkeep` (or, for Python
packages, an `__init__.py` docstring) - see root README.md's Gitignore
section for why. This is deliberate: **nothing in this folder connects to
any live Albaik website, and nothing here was copied from KFC's
implementation.**

## Isolation

- `competitors/albaik/` never imports from `competitors/kfc/` or any other
  competitor folder. Shared access is provided only through the BFF adapter contract.
- Once implemented, Albaik's database will live at
  `competitors/albaik/data/database/albaik_monitor.db` - its own file, never
  shared with or written to by another competitor's collector.

## React application

There is no brand-specific UI or official-source collector yet. When a HungerStation snapshot is available, the shared HungerStation adapter exposes this brand through the React/FastAPI application.

## Adding the real implementation later

When Albaik is implemented, the intended shape (mirroring
`competitors/kfc/`) is:

1. Research Albaik's public API/HAR captures under `research/pickup/`,
   `research/delivery/`, and `research/api-map/` - never under
   `competitors/kfc/` or any other competitor's folder.
2. Build the Node.js collector under `collector/` (replacing
   `collector/README.md`), following the same API-first,
   Playwright-bootstrap-only-when-required pattern KFC uses - see
   `competitors/kfc/README.md` "Architecture" for the pattern to follow
   (not to copy verbatim - Albaik's endpoints are unresearched and will
   differ).
3. Build the Python `backend/` (database, change detection, Excel
   export) the same way, writing only to
   `competitors/albaik/data/database/albaik_monitor.db`.
4. Add or configure a source adapter so the shared React/FastAPI application can expose the brand.
