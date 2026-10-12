"""AI mapping: what the model is sent, how its answer is validated, and the routes."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bff.ai import mapping, store
from bff.app import app
from bff.contract import Product
from bff.registry import configure_adapters_for_test


def _product(brand: str, product_id: str, name: str, price: float | None, *, available: bool | None = True) -> Product:
    return Product(
        id=product_id, brand_id=brand, source_id=product_id, name_en=name, category="Meals",
        channel="hungerstation", regular_price=price, currency="SAR", availability=available,
        description_en=f"{name} with fries and a drink", status="active",
    )


class FakeAdapter:
    def __init__(self, products: list[Product]) -> None:
        self.products = products

    def list_products(self, *, channel: str | None = None, **_: Any) -> list[Product]:
        return [product for product in self.products if channel is None or product.channel == channel]

    def get_product(self, product_id: str) -> Product | None:
        return next((product for product in self.products if product.id == product_id), None)


KUDU = _product("kudu", "hungerstation-1", "Chicken Burger Combo", 33.0)
ADAPTERS = {
    "kudu": FakeAdapter([KUDU]),
    "kfc": FakeAdapter([
        _product("kfc", "kfc-zinger", "Zinger Combo", 37.0),
        _product("kfc", "kfc-twister", "Twister Combo", 30.0),
        _product("kfc", "kfc-gone", "Old Combo", None),
    ]),
    "albaik": FakeAdapter([
        _product("albaik", "albaik-big", "Big Baik", 17.5),
        _product("albaik", "albaik-off", "Closed Item", 9.0, available=False),
    ]),
}


class FakeClient:
    def __init__(self, matches: list[dict[str, Any]], *, stop_reason: str = "end_turn") -> None:
        self.matches = matches
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps({"matches": self.matches}))],
            usage=SimpleNamespace(
                input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=40000,
            ),
        )


def _match(brand: str, ref: str, *, alternative: str = "", confidence: str = "high") -> dict[str, Any]:
    return {
        "brand_id": brand, "ref": ref, "alternative_ref": alternative, "confidence": confidence,
        "reason": f"{brand} reason", "differences": "spicy",
    }


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_DB_PATH", str(tmp_path / "ai.db"))
    monkeypatch.setenv("AI_MODEL", "claude-opus-5-5")
    configure_adapters_for_test(ADAPTERS)
    yield
    configure_adapters_for_test(None)


def test_menu_skips_unpriced_and_unavailable_items_and_never_sends_prices() -> None:
    candidates = mapping.competitor_candidates("hungerstation")
    assert [(c.ref, c.product.name_en) for c in candidates] == [
        ("kfc:1", "Twister Combo"), ("kfc:2", "Zinger Combo"), ("albaik:1", "Big Baik"),
    ]
    text = mapping.menu_text("hungerstation", candidates)
    assert "Zinger Combo" in text and "37" not in text and "17.5" not in text and "price" not in text


def test_suggest_keeps_valid_refs_and_reports_cost() -> None:
    client = FakeClient([
        _match("kfc", "kfc:2", alternative="kfc:1"),
        _match("albaik", "", confidence="none"),
    ])
    result = mapping.suggest(KUDU, "hungerstation", client=client)

    request = client.calls[0]
    assert request["fallbacks"] == "default"
    assert request["system"][1]["cache_control"] == {"type": "ephemeral"}
    sent = json.loads(request["messages"][0]["content"])
    assert sent["default_size"] == "medium" and "33" not in json.dumps(sent)

    kfc, albaik = result["matches"]
    assert kfc["product"]["id"] == "kfc-zinger" and kfc["alternative"]["id"] == "kfc-twister"
    assert kfc["confidence"] == "high" and kfc["differences"] == "spicy"
    assert albaik["product"] is None and albaik["confidence"] == "none"
    # 1000 in at $4/M + 40000 cache write at $5/M + 500 out at $20/M
    assert result["costUsd"] == pytest.approx(0.214)
    assert store.summary() == {"calls": 1, "costUsd": pytest.approx(0.214)}


def test_invented_or_cross_brand_refs_are_dropped_and_missing_brands_filled() -> None:
    result = mapping.suggest(KUDU, "hungerstation", client=FakeClient([_match("kfc", "albaik:1")]))
    kfc, albaik = result["matches"]
    assert kfc["product"] is None and kfc["confidence"] == "none"
    assert "not on this menu" in kfc["reason"]
    assert albaik["product"] is None and "no suggestion" in albaik["reason"]


def test_refusal_raises() -> None:
    with pytest.raises(mapping.AiError, match="declined"):
        mapping.suggest(KUDU, "hungerstation", client=FakeClient([], stop_reason="refusal"))


def test_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/v1/ai/status").json() == {
        "configured": False, "model": "claude-opus-5-5", "calls": 0, "costUsd": 0,
    }
    body = {"kuduProductId": "hungerstation-1", "channel": "hungerstation"}
    assert client.post("/api/v1/ai/mapping/suggest", json=body).status_code == 409
    wrong_channel = {"kuduProductId": "hungerstation-1", "channel": "delivery"}
    assert client.post("/api/v1/ai/mapping/suggest", json=wrong_channel).status_code == 404

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(mapping, "_client", lambda: FakeClient([_match("kfc", "kfc:2")]))
    response = client.post("/api/v1/ai/mapping/suggest", json=body)
    assert response.status_code == 200
    assert response.json()["matches"][0]["product"]["nameEn"] == "Zinger Combo"
