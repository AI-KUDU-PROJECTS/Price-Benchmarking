"""Collect KUDU's own HungerStation menu from the KUDU integration API.

Set KUDU_AGGREGATOR_TOKEN in .env, then run
``python manage.py collect kudu-hungerstation``. The host is on KUDU's
internal network, so the machine running this must reach it.

The API returns no images. Each item reuses the image of the same item in
the main KUDU menu (kudu/data/catalog.json), matched in this order: same
item id, same English/Arabic name, a near-identical English name, or a main
item name that starts the HungerStation name ("Orange Juice Large" ->
"Orange Juice"). Anything else stays without an image rather than showing
a wrong one.

Prints the same HUNGERSTATION_RESULT / HUNGERSTATION_ERROR lines as the
emulator collector so the Market Overview shows the outcome. A failed run
keeps the previous snapshot. The token is never printed or saved.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from kudu.catalog import CATALOG_PATH

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "hungerstation.json"
DEFAULT_URL = "https://integration.kudu.com.sa/api/aggregator/menu/kudu/hungerstation"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
SIMILAR_NAME_RATIO = 0.86


class CollectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _tokens(text: Any) -> list[str]:
    return re.findall(r"[^\W_]+", str(text or "").casefold())


def _key(text: Any) -> str:
    return "".join(_tokens(text))


class ImageIndex:
    """Look up main-menu images for HungerStation items."""

    def __init__(self, main_items: list[dict[str, Any]]) -> None:
        self.by_id: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        self.english: dict[str, str] = {}
        self.leading: list[tuple[list[str], str]] = []
        for item in main_items:
            url = item.get("itemImageUrl")
            if not url:
                continue
            self.by_id.setdefault(str(item.get("itemId")), url)
            for name in (item.get("nameEnglish"), item.get("nameArabic")):
                if _key(name):
                    self.by_name.setdefault(_key(name), url)
            tokens = _tokens(item.get("nameEnglish"))
            if tokens:
                self.english.setdefault("".join(tokens), url)
                # Very short names ("Kudu", "Fries") would match too much.
                if len(tokens) > 1 or len(tokens[0]) >= 5:
                    self.leading.append((tokens, url))

    def match(self, item: dict[str, Any]) -> tuple[str | None, str | None]:
        url = self.by_id.get(str(item.get("id")))
        if url:
            return url, "id"
        for name in (item.get("nameEnglish"), item.get("nameArabic")):
            url = self.by_name.get(_key(name))
            if url:
                return url, "name"
        key = _key(item.get("nameEnglish"))
        if key and self.english:
            best = max(self.english, key=lambda candidate: SequenceMatcher(None, key, candidate).ratio())
            if SequenceMatcher(None, key, best).ratio() >= SIMILAR_NAME_RATIO:
                return self.english[best], "similar-name"
        tokens = _tokens(item.get("nameEnglish"))
        if tokens[:1] == ["combo"]:
            tokens = tokens[1:]
        prefixes = [
            (main_tokens, url) for main_tokens, url in self.leading
            if tokens[:len(main_tokens)] == main_tokens
        ]
        if prefixes:
            return max(prefixes, key=lambda entry: len(entry[0]))[1], "leading-name"
        return None, None


def load_main_items(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return [
        item
        for categories in catalog.get("services", {}).values()
        for category in categories
        for item in category.get("items", [])
    ]


def normalize_menu(raw: Any, images: ImageIndex, retrieved_at: str) -> dict[str, Any]:
    """Keep the fields the app uses; reject anything that is not a full menu."""
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise ValueError("expected a list with one menu")
    submenus = raw[0].get("submenus")
    if not isinstance(submenus, list) or not submenus:
        raise ValueError("menu has no categories")
    categories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for submenu in submenus:
        items = submenu.get("items") if isinstance(submenu, dict) else None
        if not isinstance(items, list):
            raise ValueError("category without an item list")
        products = []
        for item in items:
            item_id = str(item.get("id", "")) if isinstance(item, dict) else ""
            if not item_id:
                raise ValueError("item without an id")
            if item_id in seen:
                raise ValueError(f"duplicate item id {item_id}")
            seen.add(item_id)
            if not item.get("nameEnglish") and not item.get("nameArabic"):
                raise ValueError(f"item {item_id} has no name")
            price = item.get("price")
            if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
                raise ValueError(f"item {item_id} has no valid price")
            image_url, image_match = images.match(item)
            products.append({
                "id": item_id,
                "nameEnglish": (item.get("nameEnglish") or "").strip() or None,
                "nameArabic": (item.get("nameArabic") or "").strip() or None,
                "descriptionEnglish": (item.get("descriptionEnglish") or "").strip() or None,
                "descriptionArabic": (item.get("descriptionArabic") or "").strip() or None,
                "price": price,
                "originalPrice": item.get("originalPrice") or None,
                "imageUrl": image_url,
                "imageMatch": image_match,
            })
        if products:
            categories.append({
                "id": str(submenu.get("id")),
                "titleEnglish": (submenu.get("titleEnglish") or "").strip() or None,
                "titleArabic": (submenu.get("titleArabic") or "").strip() or None,
                "items": products,
            })
    if not seen:
        raise ValueError("menu has no items")
    return {"retrievedAtUtc": retrieved_at, "source": "KUDU integration API", "categories": categories}


def fetch_menu(url: str, token: str) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    timeout = httpx.Timeout(60, connect=15)
    for attempt in range(3):
        try:
            response = httpx.get(url, headers=headers, timeout=timeout)
        except httpx.TransportError as error:
            if attempt == 2:
                raise CollectionError(
                    "NETWORK_UNREACHABLE",
                    "Cannot reach the KUDU integration server. It is only reachable "
                    f"from KUDU's internal network ({type(error).__name__}).",
                ) from None
        else:
            if response.status_code in (401, 403):
                raise CollectionError(
                    "AUTH_FAILED",
                    f"The KUDU integration token was rejected (HTTP {response.status_code}). "
                    "Update KUDU_AGGREGATOR_TOKEN in .env.",
                )
            if response.status_code not in RETRYABLE_STATUS or attempt == 2:
                if response.status_code != 200:
                    raise CollectionError("HTTP_ERROR", f"KUDU integration API returned HTTP {response.status_code}.")
                try:
                    return response.json()
                except ValueError:
                    raise CollectionError("INVALID_RESPONSE", "KUDU integration API did not return JSON.") from None
        time.sleep(0.5 * (2 ** attempt))
    raise CollectionError("HTTP_ERROR", "KUDU integration API retry loop did not finish.")


def save_snapshot(snapshot: dict[str, Any], path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def collect(token: str, url: str = DEFAULT_URL, path: Path | None = None) -> dict[str, Any]:
    raw = fetch_menu(url, token)
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        snapshot = normalize_menu(raw, ImageIndex(load_main_items()), retrieved_at)
    except ValueError as error:
        raise CollectionError("INVALID_RESPONSE", f"Unexpected menu from the KUDU integration API: {error}.") from None
    save_snapshot(snapshot, path or SNAPSHOT_PATH)
    return snapshot


def main() -> int:
    load_dotenv(ROOT / ".env")
    token = (os.getenv("KUDU_AGGREGATOR_TOKEN") or "").strip()
    url = (os.getenv("KUDU_AGGREGATOR_URL") or "").strip() or DEFAULT_URL
    try:
        if not token:
            raise CollectionError("TOKEN_MISSING", "KUDU_AGGREGATOR_TOKEN is not set in .env.")
        snapshot = collect(token, url)
    except CollectionError as error:
        print("HUNGERSTATION_RESULT brand=kudu status=FAILED products=0")
        print(f"HUNGERSTATION_ERROR brand=kudu code={error.code} message={error.message}")
        return 1
    items = [item for category in snapshot["categories"] for item in category["items"]]
    with_image = sum(1 for item in items if item["imageUrl"])
    print(f"KUDU HungerStation menu saved: {SNAPSHOT_PATH} | items={len(items)} with_image={with_image}")
    print(f"HUNGERSTATION_RESULT brand=kudu status=SUCCESS products={len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
