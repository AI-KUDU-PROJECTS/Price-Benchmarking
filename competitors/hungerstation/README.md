# HungerStation mobile collection

This module collects the six configured restaurant menus from the
HungerStation Android app and stores them in one historical SQLite database.
It is independent from the official website collectors.

## Manual runs

Start the Android emulator, sign in to HungerStation if required, and keep the
configured Riyadh delivery location selected. From the repository root:

```bash
.venv/bin/python manage.py collect hungerstation --brand kfc
.venv/bin/python manage.py collect hungerstation --all
```

Configured restaurants: KFC, Hardee's, Burger King, Herfy, McDonald's, and
AlBaik. A failed restaurant does not replace its last successful snapshot and
does not stop the remaining restaurants.

Use at least 4 GB RAM for the Android virtual device. The collector uses the
Appium Settings location service, when available, to keep the emulator at the
configured Riyadh coordinates (`HUNGERSTATION_LATITUDE` and
`HUNGERSTATION_LONGITUDE`) across restarts. If HungerStation asks for a new
delivery address, the collector can confirm the detected location and continue.

For Android emulators, the collector sets the configured Riyadh GPS position
before launching HungerStation. Override it with `HUNGERSTATION_LATITUDE` and
`HUNGERSTATION_LONGITUDE` when another fixed delivery area is required.

### Optional Claude navigation recovery

The collector normally navigates with deterministic Android accessibility
selectors. If those rules cannot reach search or identify a restaurant result,
an optional Claude Sonnet vision fallback can inspect the current screenshot
and compact UI hierarchy and request one bounded ADB action. It cannot type
arbitrary text, run shell commands, extract prices, add items to a cart, or
place an order. The deterministic parser still validates and stores all menu
data.

Configure the fallback in the local `.env` file:

```dotenv
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5-5
ANTHROPIC_EFFORT=medium
HUNGERSTATION_AI_NAVIGATION=true
HUNGERSTATION_AI_MAX_ACTIONS=6
```

The key is optional and `.env` is excluded from Git. When the key or feature
flag is absent, collection behaves exactly as before. AI recovery actions are
logged as `HUNGERSTATION_AI_ACTION`; API failures fall back to the existing
collector error without replacing the last complete snapshot.

Each live run also captures the product artwork shown inside the HungerStation
menu card. Images are stored under `data/images/<brand>/`, exposed by the BFF
at `/hungerstation-images/<brand>/<product>.jpg`, and reused by both menu and
promotion responses. Set `HUNGERSTATION_IMAGE_DIR` to move this storage. On
AWS, point it at persistent storage (or replace the static mount with object
storage) so images survive application redeployments.

## Daily scheduler

```bash
.venv/bin/python manage.py schedule hungerstation
```

The default time is 23:00 Asia/Riyadh. Configure it with
`HUNGERSTATION_DAILY_RUN_TIME` and `HUNGERSTATION_ENABLE_SCHEDULER`.

## AWS upload

Local SQLite remains the default. Set `HUNGERSTATION_UPLOAD_URL` and
`HUNGERSTATION_UPLOAD_TOKEN` to send every successful normalized snapshot to
an authenticated internal API after it is saved locally.
