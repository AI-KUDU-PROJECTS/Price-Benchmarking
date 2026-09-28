"""Optional upload of a completed mobile snapshot to an AWS-hosted API."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from competitors.hungerstation import config


def upload(payload: dict[str, Any]) -> bool:
    if not config.UPLOAD_URL:
        return False
    headers = {"Content-Type": "application/json"}
    if config.UPLOAD_TOKEN:
        headers["Authorization"] = f"Bearer {config.UPLOAD_TOKEN}"
    request = urllib.request.Request(
        config.UPLOAD_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - configured internal endpoint
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Upload failed with HTTP {response.status}")
    return True
