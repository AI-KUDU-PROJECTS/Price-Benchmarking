"""
competitors/hardees/backend/schema_validator.py
---------------------------------------------------------------------
Python-side mirror of collector/api-client.js's response validation (see
api-map.md "Schema validation"). This is the boundary check run_service.py
applies to whatever JSON the Node collector wrote to disk, BEFORE any of it
is trusted enough to reach the database - a second, independent layer so a
bug or future change on either side of the Node/Python boundary can't
silently corrupt the database with half-shaped rows.
---------------------------------------------------------------------
"""
from __future__ import annotations

from typing import Any

REQUIRED_CHANNEL_KEYS = ("channel", "status", "branchId", "branchName", "categoryResults", "products")
VALID_STATUSES = ("SUCCESS", "PARTIAL", "FAILED")
VALID_CHANNELS = ("PICKUP", "DELIVERY")

REQUIRED_PRODUCT_KEYS_ANY_OF = ("id", "name")  # a product row must carry at least one usable identity/display field


class SchemaValidationError(ValueError):
    pass


def validate_channel_result(data: dict[str, Any]) -> list[str]:
    """Returns a list of problems found (empty list = valid). Never raises -
    callers decide whether any problem is fatal."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["channel result is not a JSON object"]

    for key in REQUIRED_CHANNEL_KEYS:
        if key not in data:
            problems.append(f"missing required key: {key}")

    status = data.get("status")
    if status not in VALID_STATUSES:
        problems.append(f"invalid status: {status!r} (expected one of {VALID_STATUSES})")

    channel = data.get("channel")
    if channel not in VALID_CHANNELS:
        problems.append(f"invalid channel: {channel!r} (expected one of {VALID_CHANNELS})")

    products = data.get("products")
    if products is not None and not isinstance(products, list):
        problems.append("'products' is present but is not a list")
    elif isinstance(products, list):
        for i, p in enumerate(products):
            if not isinstance(p, dict):
                problems.append(f"products[{i}] is not an object")
                continue
            if not any(k in p and p[k] not in (None, "") for k in REQUIRED_PRODUCT_KEYS_ANY_OF):
                problems.append(f"products[{i}] has neither 'id' nor 'name' - cannot be identified")

    category_results = data.get("categoryResults")
    if category_results is not None and not isinstance(category_results, list):
        problems.append("'categoryResults' is present but is not a list")

    return problems


def is_usable(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """A channel result is "usable" (safe to ingest, even if PARTIAL/FAILED
    for record-keeping) as long as it's structurally sound - status/channel
    validity and a well-shaped products list. FAILED results with an empty
    products list are still usable (there's just nothing to ingest)."""
    problems = validate_channel_result(data)
    # Only structural problems (not-a-list, wrong types) block ingestion;
    # a FAILED/PARTIAL status by itself is not a structural problem.
    blocking = [p for p in problems if "invalid status" not in p]
    return (len(blocking) == 0, problems)
