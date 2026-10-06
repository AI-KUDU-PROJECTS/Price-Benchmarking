from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
from PIL import Image

from competitors.hungerstation import collector, config
from competitors.hungerstation.ai_navigation import (
    AnthropicNavigator,
    NavigationAction,
    compact_ui_hierarchy,
)
from competitors.hungerstation.collector import AndroidDevice
from competitors.hungerstation.config import RESTAURANT_BY_ID


def _screenshot() -> bytes:
    image = Image.new("RGB", (1080, 2400), color=(245, 245, 245))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_compact_ui_hierarchy_keeps_navigation_evidence() -> None:
    compact = compact_ui_hierarchy(
        """
        <hierarchy>
          <node class="android.widget.EditText" resource-id="app:id/input_csc"
                text="ابحث" clickable="true" bounds="[20,100][1060,220]" />
        </hierarchy>
        """
    )
    assert "input_csc" in compact
    assert "ابحث" in compact
    assert "[20,100][1060,220]" in compact


def test_anthropic_navigator_returns_one_validated_tool_action() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "claude-sonnet-5-5"
        assert payload["output_config"]["effort"] == config.ANTHROPIC_EFFORT
        assert payload["messages"][0]["content"][0]["type"] == "image"
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "tap",
                        "input": {"x": 540, "y": 900},
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        action = AnthropicNavigator(
            api_key="test-key",
            model="claude-sonnet-5-5",
            client=client,
        ).choose_action(
            screenshot=_screenshot(),
            ui_xml="<hierarchy />",
            restaurant_name="KFC",
            search_term="kfc",
            phase="find_and_open_restaurant_result",
            action_history=[],
        )
    assert action == NavigationAction("tap", {"x": 540, "y": 900})


def test_anthropic_navigator_rejects_out_of_bounds_coordinates() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "tap",
                        "input": {"x": 5000, "y": 900},
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        action = AnthropicNavigator(api_key="test-key", client=client).choose_action(
            screenshot=_screenshot(),
            ui_xml="<hierarchy />",
            restaurant_name="KFC",
            search_term="kfc",
            phase="reach_restaurant_search",
            action_history=[],
        )
    assert action is None


def test_android_dump_reads_completed_device_file(monkeypatch) -> None:
    device = AndroidDevice(Path("adb"), "emulator-test")
    calls: list[tuple[str, ...]] = []

    def run(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("exec-out", "cat"):
            return '<hierarchy><node text="ready" /></hierarchy>\n'
        return "UI hierarchy dumped"

    monkeypatch.setattr(device, "run", run)
    assert "ready" in device.dump()
    assert ("exec-out", "cat", "/data/local/tmp/hungerstation-window.xml") in calls


def test_android_device_detects_focused_anr_even_without_ui_xml(monkeypatch) -> None:
    device = AndroidDevice(Path("adb"), "emulator-test")
    monkeypatch.setattr(
        device,
        "run",
        lambda *_args: (
            "mCurrentFocus=Window{abc u0 Application Not Responding: "
            "com.hungerstation.android.web}"
        ),
    )
    assert device.has_app_error()


def test_ai_recovery_executes_bounded_action_and_rechecks_screen(monkeypatch) -> None:
    ready_xml = (
        '<hierarchy><node resource-id="com.hungerstation.android.web:id/input_csc" '
        'bounds="[0,0][1080,200]" /></hierarchy>'
    )

    class FakeNavigator:
        available = True

        def choose_action(self, **_kwargs) -> NavigationAction:
            return NavigationAction("tap", {"x": 540, "y": 100})

    class FakeDevice:
        tapped: list[tuple[int, int]] = []

        def has_app_error(self) -> bool:
            return False

        def screenshot(self) -> bytes:
            return _screenshot()

        def tap(self, x: int, y: int) -> None:
            self.tapped.append((x, y))

        def dump(self) -> str:
            return ready_xml

    monkeypatch.setattr(config, "AI_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(config, "AI_MAX_ACTIONS", 2)
    monkeypatch.setattr(collector, "AnthropicNavigator", FakeNavigator)
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)
    device = FakeDevice()
    recovered = collector._ai_recover(
        device,  # type: ignore[arg-type]
        RESTAURANT_BY_ID["kfc"],
        phase="reach_restaurant_search",
        ready=collector._has_search_input,
    )
    assert recovered == ready_xml
    assert device.tapped == [(540, 100)]


def test_ai_search_waits_for_transition_and_clears_in_one_adb_call(monkeypatch) -> None:
    search_xml = (
        '<hierarchy><node resource-id="com.hungerstation.android.web:id/input_csc" '
        'bounds="[50,100][1030,250]" /></hierarchy>'
    )

    class FakeDevice:
        taps: list[tuple[int, int]] = []
        runs: list[tuple[str, ...]] = []
        keys: list[str] = []

        def tap(self, x: int, y: int) -> None:
            self.taps.append((x, y))

        def dump(self) -> str:
            return search_xml

        def has_app_error(self) -> bool:
            return False

        def key(self, code: str) -> None:
            self.keys.append(code)

        def run(self, *args: str) -> str:
            self.runs.append(args)
            return ""

    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)
    device = FakeDevice()
    collector._apply_ai_action(
        device,  # type: ignore[arg-type]
        NavigationAction("search_restaurant", {"x": 500, "y": 180}),
        RESTAURANT_BY_ID["kfc"],
        width=1080,
        height=2400,
    )
    clear_calls = [call for call in device.runs if call[:3] == ("shell", "input", "keyevent")]
    assert len(clear_calls) == 1
    assert clear_calls[0][3:] == tuple(["67"] * 60)
    assert ("shell", "input", "text", "kfc") in device.runs
    assert device.taps == [(500, 180), (540, 175)]
    assert device.keys == ["123", "66"]
