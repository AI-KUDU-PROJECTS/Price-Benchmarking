from types import SimpleNamespace
import pytest

from fastapi.testclient import TestClient

from bff.app import app
from bff import pull_all, routes


def test_albaik_channels_are_separate_sequential_targets():
    assert [target.id for target in pull_all.ALBAIK_APP_TARGETS] == ["albaik-pickup", "albaik-delivery"]
    assert pull_all.albaik_app_pull_manager.max_workers == 1


def test_app_status_endpoint_does_not_share_hungerstation_state(monkeypatch):
    manager = pull_all.PullManager(targets=pull_all.ALBAIK_APP_TARGETS, runner=lambda *_: ("success", "Collected."), max_workers=1)
    monkeypatch.setattr(routes, "albaik_app_pull_manager", manager)
    monkeypatch.setattr("competitors.albaik.backend.app_store.latest_collection_status", lambda run: run)
    client = TestClient(app)
    assert client.get("/api/v1/market/albaik-app/pull").json() == {"run": None}
    response = client.post("/api/v1/market/albaik-app/pull")
    assert response.status_code == 202
    assert [row["id"] for row in response.json()["run"]["brands"]] == ["albaik-pickup", "albaik-delivery"]


@pytest.mark.parametrize("suffix", ["", " excluded=1", " excluded=1 skipped=2"])
def test_app_success_requires_confirmed_channel_and_zero_exit(tmp_path,monkeypatch,suffix):
    monkeypatch.setattr(pull_all,"LOG_DIR",tmp_path)
    def run(*_,**kwargs):
        kwargs["stdout"].write(f"ALBAIK_RESULT channel=PICKUP status=SUCCESS products=90 images_new=4{suffix}\n")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(pull_all.subprocess,"run",run)
    result=pull_all.PullManager._run_subprocess(pull_all.ALBAIK_APP_TARGETS[0],"batch")
    assert result==("success","Collected 90 products; 4 new images saved." +
                    (" 1 product(s) excluded as requested." if suffix else "") +
                    (" 2 product(s) could not open after two attempts and were skipped." if "skipped" in suffix else ""))


def test_app_failure_preserves_actionable_reason_after_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(pull_all,"LOG_DIR",tmp_path)
    monkeypatch.setattr(pull_all.time,"sleep",lambda _:None)
    calls=[]
    def run(*_,**kwargs):
        calls.append(1)
        kwargs["stdout"].write("ALBAIK_ERROR channel=DELIVERY code=LOGIN_REQUIRED message=Sign in to select a delivery address.\n")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(pull_all.subprocess,"run",run)
    status,message=pull_all.PullManager._run_subprocess(pull_all.ALBAIK_APP_TARGETS[1],"batch")
    assert status=="failed"
    assert len(calls)==2
    assert "LOGIN_REQUIRED" in message and "Sign in" in message
