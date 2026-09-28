"""Transient production API failures should not discard a complete KUDU snapshot."""
from __future__ import annotations

import httpx
import pytest

from kudu import refresh


def test_kudu_get_retries_transient_http_error(monkeypatch) -> None:
    statuses = [503, 200]
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(statuses.pop(0), json={"data": []})

    monkeypatch.setattr(refresh.time, "sleep", lambda seconds: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        response = refresh._get(client, "menuList", {"templateId": 1, "servicesType": "delivery"})
    assert response.status_code == 200
    assert len(requests) == 2


def test_kudu_get_does_not_retry_auth_error(monkeypatch) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "unauthorized"})

    monkeypatch.setattr(refresh.time, "sleep", lambda seconds: pytest.fail("401 must not be retried"))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        response = refresh._get(client, "menuList", {"templateId": 1})
    with pytest.raises(httpx.HTTPStatusError):
        refresh._data(response, "menuList")
    assert calls == 1
