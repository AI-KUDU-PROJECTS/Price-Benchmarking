"""Collect configured restaurant menus from the HungerStation Android app."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image

from competitors.hungerstation import config, database
from competitors.hungerstation.ai_navigation import AnthropicNavigator, NavigationAction
from competitors.hungerstation.config import Restaurant
from competitors.hungerstation.uploader import upload

PACKAGE = "com.hungerstation.android.web"
MAIN_ACTIVITY = f"{PACKAGE}/.hungeractivities.MainActivity"
CURRENCY_LABELS = {"§", "SAR", "ر.س"}


class CollectionFailure(RuntimeError):
    """A stable machine code plus a safe, user-facing failure explanation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.user_message = " ".join(message.split())[:500]
        super().__init__(self.user_message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _adb_candidates() -> Iterable[Path]:
    executable = shutil.which("adb")
    if executable:
        yield Path(executable)
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(name)
        if value:
            yield Path(value) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    yield from Path("/mnt/c/Users").glob("*/AppData/Local/Android/Sdk/platform-tools/adb.exe")


def find_adb(explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"ADB was not found at {candidate}")
    for candidate in _adb_candidates():
        if candidate.exists():
            return candidate
    raise FileNotFoundError("ADB was not found. Install Android SDK Platform Tools or pass --adb.")


class AndroidDevice:
    def __init__(self, adb: Path, serial: str) -> None:
        self.adb = adb
        self.serial = serial
        self._screen_size: tuple[int, int] | None = None

    def run(self, *args: str, attempts: int = 3) -> str:
        last_error: subprocess.SubprocessError | None = None
        for attempt in range(max(1, attempts)):
            try:
                completed = subprocess.run(
                    [str(self.adb), "-s", self.serial, *args],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=config.ADB_COMMAND_TIMEOUT,
                )
                return completed.stdout
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                last_error = error
                time.sleep(0.8 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def wait_until_ready(self) -> None:
        """Fail early when ADB is connected but Android has not finished booting."""
        last_state = "unknown"
        for attempt in range(12):
            try:
                last_state = self.run("get-state", attempts=1).strip()
                booted = self.run(
                    "shell", "getprop", "sys.boot_completed", attempts=1
                ).strip()
                if last_state == "device" and booted == "1":
                    return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                stderr = getattr(error, "stderr", "") or ""
                last_state = stderr.strip() or type(error).__name__
            time.sleep(min(0.5 * (attempt + 1), 2.0))
        raise RuntimeError(
            f"Android emulator {self.serial} is not ready (last state: {last_state})."
        )

    def screen_size(self) -> tuple[int, int]:
        """Return the current device dimensions instead of assuming 1080x2400."""
        if self._screen_size is not None:
            return self._screen_size
        output = self.run("shell", "wm", "size")
        matches = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
        if matches:
            width, height = map(int, matches[-1])
        else:
            with Image.open(io.BytesIO(self.screenshot())) as opened:
                width, height = opened.size
        self._screen_size = (width, height)
        return self._screen_size

    def run_bytes(self, *args: str, attempts: int = 3) -> bytes:
        last_error: subprocess.SubprocessError | None = None
        for attempt in range(max(1, attempts)):
            try:
                completed = subprocess.run(
                    [str(self.adb), "-s", self.serial, *args],
                    check=True,
                    capture_output=True,
                    timeout=config.ADB_COMMAND_TIMEOUT,
                )
                return completed.stdout
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                last_error = error
                time.sleep(0.8 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(x), str(y))
        time.sleep(0.8)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> None:
        self.run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))
        time.sleep(0.7)

    def key(self, code: str) -> None:
        self.run("shell", "input", "keyevent", code)
        time.sleep(0.5)

    def dump(self) -> str:
        last_output = ""
        max_attempts = 6
        for attempt in range(max_attempts):
            # Writing to /dev/tty is unreliable with some Windows/WSL ADB
            # combinations and can return only a few bytes despite exit 0.
            # Dump to a device file first, then transfer the completed XML.
            try:
                self.run("shell", "uiautomator", "dump", "/data/local/tmp/hungerstation-window.xml")
                last_output = self.run(
                    "exec-out", "cat", "/data/local/tmp/hungerstation-window.xml"
                )
            except subprocess.CalledProcessError:
                last_output = self.run("exec-out", "uiautomator", "dump", "/dev/tty")
            end = last_output.rfind("</hierarchy>")
            if end >= 0:
                hierarchy = last_output[: end + len("</hierarchy>")]
                try:
                    ET.fromstring(hierarchy)
                except ET.ParseError:
                    pass
                else:
                    return hierarchy
            time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(
            f"Android returned an incomplete UI hierarchy after {max_attempts} attempts "
            f"({len(last_output)} bytes)"
        )

    def screenshot(self) -> bytes:
        last_error: OSError | None = None
        for attempt in range(3):
            payload = self.run_bytes("exec-out", "screencap", "-p")
            try:
                with Image.open(io.BytesIO(payload)) as screenshot:
                    screenshot.verify()
                return payload
            except OSError as error:
                last_error = error
                time.sleep(0.8 * (attempt + 1))
        raise RuntimeError("Android returned an invalid screenshot after 3 attempts") from last_error

    def has_app_error(self) -> bool:
        """Check the focused Android window even when UI Automator is unavailable."""
        try:
            # The full `dumpsys window` output can retain a stale per-display
            # `currentFocus` entry after an ANR dialog disappears. The
            # `displays` section exposes the active mCurrentFocus instead.
            windows = self.run("shell", "dumpsys", "window", "displays")
        except subprocess.CalledProcessError:
            return False
        for line in windows.splitlines():
            lowered = line.casefold()
            if "mcurrentfocus=" not in lowered and "mfocusedwindow=" not in lowered:
                continue
            if PACKAGE in line and (
                "application not responding" in lowered
                or "application error" in lowered
                or "has stopped" in lowered
            ):
                return True
        return False

    def start_app(self) -> None:
        self.wait_until_ready()
        if self.serial.startswith("emulator-"):
            try:
                self.run(
                    "shell", "appops", "set", "io.appium.settings",
                    "android:mock_location", "allow",
                    attempts=1,
                )
                self.run(
                    "shell", "am", "start-foreground-service",
                    "-n", "io.appium.settings/.LocationService",
                    "--es", "longitude", str(config.LONGITUDE),
                    "--es", "latitude", str(config.LATITUDE),
                    attempts=1,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                self.run(
                    "emu", "geo", "fix",
                    str(config.LONGITUDE), str(config.LATITUDE),
                    attempts=2,
                )
            time.sleep(0.5)
        self.run("shell", "am", "force-stop", PACKAGE)
        self.run("shell", "am", "start", "-n", MAIN_ACTIVITY)
        time.sleep(5.0)


def _normalize(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    return tuple(map(int, match.groups())) if match else None  # type: ignore[return-value]


def _labels(root: ET.Element) -> list[tuple[str, str]]:
    labels: list[tuple[str, str]] = []
    for node in root.iter("node"):
        label = (node.attrib.get("content-desc") or "").strip()
        if label:
            labels.append((node.attrib.get("resource-id") or "", label))
    return labels


def _has_search_input(xml: str) -> bool:
    return "com.hungerstation.android.web:id/input_csc" in xml


def _find_search_input(xml: str) -> tuple[int, int] | None:
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if node.attrib.get("resource-id", "").endswith("/input_csc"):
            box = _bounds(node.attrib.get("bounds", ""))
            if box:
                return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _find_menu_search_close(xml: str) -> tuple[int, int] | None:
    """Find the close control for the restaurant menu's internal search overlay."""
    if "menuSearchInput" not in xml:
        return None
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if node.attrib.get("resource-id") != "menuSearchCloseButton":
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _find_location_recovery(xml: str) -> tuple[int, int] | None:
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        resource_id = node.attrib.get("resource-id", "")
        label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").casefold()
        if resource_id.endswith("/tooltip_message"):
            return (1000, 500)
        if resource_id.endswith("/confirm_drop_off_button") or "confirm location" in label:
            box = _bounds(node.attrib.get("bounds", ""))
            if box:
                return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        if not (
            resource_id.endswith("/empty_state_primary_button")
            or "select a new location" in label
        ):
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _find_location_setup_action(xml: str) -> tuple[int, int] | None:
    root = ET.fromstring(xml)
    for suffix in ("/confirm_drop_off_button", "/detect_my_location", "/change_location_header_v2"):
        if suffix == "/change_location_header_v2" and "Select your location" not in xml:
            continue
        for node in root.iter("node"):
            if not node.attrib.get("resource-id", "").endswith(suffix):
                continue
            if suffix == "/confirm_drop_off_button" and (
                node.attrib.get("clickable") != "true"
                or node.attrib.get("enabled") == "false"
            ):
                continue
            box = _bounds(node.attrib.get("bounds", ""))
            if box:
                return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _has_android_app_error(xml: str) -> bool:
    """Detect Android crash/ANR dialogs before trying app-specific selectors."""
    lowered = xml.casefold()
    return (
        "android:id/aerr_close" in xml
        or "android:id/aerr_wait" in xml
        or "isn't responding" in lowered
        or "keeps stopping" in lowered
    )


def _clickable_restaurants(root: ET.Element) -> Iterable[tuple[ET.Element, list[tuple[str, ET.Element]]]]:
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        titles: list[tuple[str, ET.Element]] = []
        for child in node.iter("node"):
            resource_id = child.attrib.get("resource-id", "")
            if resource_id.endswith("/title"):
                value = (child.attrib.get("text") or child.attrib.get("content-desc") or "").strip()
                if value:
                    titles.append((value, child))
        if titles:
            yield node, titles


def _find_restaurant_result(xml: str, restaurant: Restaurant) -> tuple[int, int, str] | None:
    aliases = {_normalize(alias) for alias in restaurant.aliases}
    root = ET.fromstring(xml)
    candidates: list[tuple[int, ET.Element, str]] = []
    for node, titles in _clickable_restaurants(root):
        for title, title_node in titles:
            normalized = _normalize(title)
            score = 2 if normalized in aliases else 1 if any(alias in normalized for alias in aliases) else 0
            if score:
                candidates.append((score, title_node, title))
    for _, title_node, title in sorted(candidates, key=lambda item: item[0], reverse=True):
        box = _bounds(title_node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2, title)
    return None


def _find_first_restaurant_card(xml: str, restaurant: Restaurant) -> tuple[int, int, str] | None:
    """Use the first full result when HungerStation omits its title from accessibility."""
    root = ET.fromstring(xml)
    cards: list[tuple[int, tuple[int, int, int, int]]] = []
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        resource_ids = {child.attrib.get("resource-id", "") for child in node.iter("node")}
        if not any(value.endswith("/description") for value in resource_ids):
            continue
        if not any(value.endswith("/rate_value") for value in resource_ids):
            continue
        if not any(value.endswith("/product_name") for value in resource_ids):
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box and box[2] - box[0] >= 800 and box[3] - box[1] >= 400:
            cards.append((box[1], box))
    if not cards:
        return None
    _, box = min(cards, key=lambda card: card[0])
    return ((box[0] + box[2]) // 2, min(box[1] + 80, box[3] - 1), restaurant.name)


def _find_popular_search_shortcut(xml: str, restaurant: Restaurant) -> tuple[int, int] | None:
    targets = {_normalize(restaurant.search_term), *(_normalize(alias) for alias in restaurant.aliases)}
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if not node.attrib.get("resource-id", "").startswith("UniversalSearch_popular_search_cell_"):
            continue
        label = node.attrib.get("content-desc") or node.attrib.get("text") or ""
        if _normalize(label) not in targets:
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _find_search_suggestion(xml: str, restaurant: Restaurant) -> tuple[int, int] | None:
    aliases = {_normalize(alias) for alias in restaurant.aliases}
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if node.attrib.get("clickable") != "true":
            continue
        if any(
            child.attrib.get("resource-id", "").endswith("/input_csc")
            for child in node.iter("node")
        ):
            continue
        values: list[str] = []
        for child in node.iter("node"):
            values.extend((child.attrib.get("text", ""), child.attrib.get("content-desc", "")))
        normalized_values = {_normalize(value) for value in values if value}
        if not any(alias in value for alias in aliases for value in normalized_values):
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _find_autocomplete_shortcut(xml: str, restaurant: Restaurant) -> tuple[int, int] | None:
    targets = {_normalize(restaurant.search_term), *(_normalize(alias) for alias in restaurant.aliases)}
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if not node.attrib.get("resource-id", "").startswith("UniversalSearch_autocomplete_cell_"):
            continue
        label = node.attrib.get("content-desc") or node.attrib.get("text") or ""
        first_suggestion = _normalize(label.split(",", 1)[0])
        if first_suggestion not in targets:
            continue
        box = _bounds(node.attrib.get("bounds", ""))
        if box:
            return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


def _is_restaurant_menu(xml: str, restaurant: Restaurant) -> bool:
    aliases = {_normalize(alias) for alias in restaurant.aliases}
    root = ET.fromstring(xml)
    header_values: list[str] = []
    for node in root.iter("node"):
        box = _bounds(node.attrib.get("bounds", ""))
        if box is not None and box[1] < 800:
            header_values.extend((node.attrib.get("text", ""), node.attrib.get("content-desc", "")))
    normalized_headers = {_normalize(value) for value in header_values if value}
    matches_brand = any(alias in value for alias in aliases for value in normalized_headers)
    has_product = any(
        parse_accessibility_label(
            node.attrib.get("content-desc", ""),
            restaurant.id,
            node.attrib.get("resource-id", ""),
        )
        is not None
        for node in root.iter("node")
    )
    # Flutter has changed the root scrollable class between releases. Product
    # evidence plus the target brand in the header is a stronger invariant
    # than a particular Android widget implementation.
    return matches_brand and ("Min. Order" in xml or has_product)


def _is_active_menu_page(xml: str, brand_id: str) -> bool:
    if PACKAGE not in xml:
        return False
    root = ET.fromstring(xml)
    has_product = bool(parse_split_accessibility_products(xml, brand_id)) or any(
        parse_accessibility_label(
            node.attrib.get("content-desc", ""),
            brand_id,
            node.attrib.get("resource-id", ""),
        )
        is not None
        for node in root.iter("node")
    )
    return has_product or (
        "Min. Order" in xml and "android.widget.ScrollView" in xml
    )


def _replace_search_text(
    device: AndroidDevice,
    restaurant: Restaurant,
    *,
    submit: bool = True,
) -> None:
    device.key("123")  # KEYCODE_MOVE_END
    # Android's input command accepts multiple key codes. Send the clears in
    # one ADB round-trip; 60 separate subprocesses are slow enough to trigger
    # an ANR while the search screen is transitioning.
    device.run("shell", "input", "keyevent", *(["67"] * 60))  # KEYCODE_DEL
    encoded = restaurant.search_term.replace(" ", "%s")
    device.run("shell", "input", "text", encoded)
    time.sleep(0.8)
    if submit:
        device.key("66")  # KEYCODE_ENTER


def _apply_ai_action(
    device: AndroidDevice,
    action: NavigationAction,
    restaurant: Restaurant,
    *,
    width: int,
    height: int,
) -> None:
    if action.name == "tap":
        device.tap(action.arguments["x"], action.arguments["y"])
        time.sleep(1.5)
    elif action.name == "search_restaurant":
        device.tap(action.arguments["x"], action.arguments["y"])
        time.sleep(2.5)
        try:
            transitioned_xml = device.dump()
        except RuntimeError:
            return
        transitioned_point = _find_search_input(transitioned_xml)
        if transitioned_point is None or device.has_app_error():
            return
        device.tap(*transitioned_point)
        _replace_search_text(device, restaurant, submit=False)
        time.sleep(1.5)
        try:
            suggestion_xml = device.dump()
        except RuntimeError:
            return
        suggestion = (
            _find_autocomplete_shortcut(suggestion_xml, restaurant)
            or _find_search_suggestion(suggestion_xml, restaurant)
        )
        if suggestion is not None:
            device.tap(*suggestion)
        else:
            device.key("66")
    elif action.name == "swipe":
        center = width // 2
        top, bottom = int(height * 0.28), int(height * 0.78)
        if action.arguments["direction"] == "up":
            device.swipe(center, bottom, center, top, 550)
        else:
            device.swipe(center, top, center, bottom, 550)
    elif action.name == "back":
        device.key("4")  # KEYCODE_BACK
    elif action.name == "wait":
        time.sleep(3.0)
    elif action.name == "restart_app":
        device.start_app()


def _ui_signature(xml: str) -> str:
    """Stable-enough fingerprint used to tell Claude whether an action worked."""
    if not xml:
        return "unavailable"
    evidence = re.sub(r'\b(?:bounds|index)="[^"]*"', "", xml)
    return hashlib.sha256(evidence.encode("utf-8", errors="replace")).hexdigest()[:12]


def _is_black_screen(screenshot: bytes) -> bool:
    """Detect the unusable Flutter black frame seen when rendering stalls."""
    with Image.open(io.BytesIO(screenshot)) as opened:
        grayscale = opened.convert("L")
        grayscale.thumbnail((90, 200))
        pixels = list(grayscale.getdata())
    if not pixels:
        return False
    dark_ratio = sum(value < 18 for value in pixels) / len(pixels)
    return dark_ratio >= 0.90


def _ai_recover(
    device: AndroidDevice,
    restaurant: Restaurant,
    *,
    phase: str,
    ready: Callable[[str], bool],
    initial_xml: str = "",
) -> str | None:
    """Use bounded vision actions and report the outcome of every action."""
    if not config.AI_NAVIGATION_ENABLED:
        return None
    navigator = AnthropicNavigator()
    if not navigator.available:
        return None

    xml = initial_xml
    action_history: list[str] = []
    unchanged_actions: dict[tuple[str, str], int] = {}
    black_screen_recoveries = 0
    for _ in range(config.AI_MAX_ACTIONS):
        if xml and ready(xml):
            return xml
        menu_search_close = _find_menu_search_close(xml) if xml else None
        if menu_search_close is not None:
            print(
                f"HUNGERSTATION_ANDROID_RECOVERY phase={phase} "
                "reason=menu-search-overlay action=close"
            )
            device.tap(*menu_search_close)
            action_history.append("system_close_menu_search")
            try:
                xml = device.dump()
            except RuntimeError:
                xml = ""
            continue
        if device.has_app_error():
            print(
                f"HUNGERSTATION_ANDROID_RECOVERY phase={phase} "
                "reason=focused-app-error action=restart-app"
            )
            device.start_app()
            action_history.append("system_restart_app")
            try:
                xml = device.dump()
            except RuntimeError:
                xml = ""
            continue
        try:
            screenshot = device.screenshot()
            if _is_black_screen(screenshot):
                black_screen_recoveries += 1
                if black_screen_recoveries == 1:
                    print(
                        f"HUNGERSTATION_ANDROID_RECOVERY phase={phase} "
                        "reason=black-screen action=back"
                    )
                    device.key("4")
                    action_history.append("system_back:black_screen")
                elif black_screen_recoveries == 2:
                    print(
                        f"HUNGERSTATION_ANDROID_RECOVERY phase={phase} "
                        "reason=black-screen action=restart-app"
                    )
                    device.start_app()
                    action_history.append("system_restart_app:black_screen")
                else:
                    raise CollectionFailure(
                        "APP_BLACK_SCREEN",
                        f"HungerStation stayed on a black screen during {phase} after "
                        "closing the keyboard and restarting the app.",
                    )
                try:
                    xml = device.dump()
                except RuntimeError:
                    xml = ""
                continue
            with Image.open(io.BytesIO(screenshot)) as opened:
                width, height = opened.size
            action = navigator.choose_action(
                screenshot=screenshot,
                ui_xml=xml,
                restaurant_name=restaurant.name,
                search_term=restaurant.search_term,
                phase=phase,
                action_history=action_history,
            )
        except CollectionFailure:
            raise
        except Exception as error:
            detail = " ".join(str(error).split())[:240] or type(error).__name__
            print(
                f"HUNGERSTATION_AI_WARNING phase={phase} "
                f"error={type(error).__name__}: {detail}"
            )
            raise CollectionFailure(
                "AI_NAVIGATION_UNAVAILABLE",
                f"Sonnet navigation was unavailable during {phase}: {detail}",
            ) from error
        if action is None:
            raise CollectionFailure(
                "AI_NO_SAFE_ACTION",
                f"Sonnet could not identify a safe next step during {phase}.",
            )
        if action.name == "report_blocker":
            detail = action.arguments["detail"]
            code = action.arguments["code"]
            print(
                f"HUNGERSTATION_AI_BLOCKER phase={phase} code={code} detail={detail}"
            )
            raise CollectionFailure(
                f"AI_{code}",
                f"Sonnet identified a blocking screen during {phase}: {detail}",
            )
        before = _ui_signature(xml)
        print(f"HUNGERSTATION_AI_ACTION phase={phase} action={action.name}")
        _apply_ai_action(
            device,
            action,
            restaurant,
            width=width,
            height=height,
        )
        try:
            updated_xml = device.dump()
        except RuntimeError:
            updated_xml = ""
        after = _ui_signature(updated_xml)
        outcome = "changed" if after != before else "no_change"
        action_history.append(f"{action.name}:{outcome}")
        key = (action.name, before)
        unchanged_actions[key] = unchanged_actions.get(key, 0) + (outcome == "no_change")
        if unchanged_actions[key] >= 2:
            action_history.append(
                f"blocked:{action.name} already repeated on this unchanged screen; choose another action"
            )
        xml = updated_xml
    # A restaurant menu can finish rendering just after the final bounded AI
    # action. Poll without issuing more actions so a successful late
    # transition is not reported as "restaurant not found".
    for _ in range(5):
        if xml and ready(xml):
            return xml
        time.sleep(1.5)
        try:
            xml = device.dump()
        except RuntimeError:
            xml = ""
        if device.has_app_error():
            break
    if xml and ready(xml):
        return xml
    raise CollectionFailure(
        "AI_ACTION_LIMIT",
        f"Sonnet could not reach the expected screen during {phase} after "
        f"{config.AI_MAX_ACTIONS} adaptive actions.",
    )


def open_restaurant(device: AndroidDevice, restaurant: Restaurant) -> str:
    device.start_app()
    try:
        xml = device.dump()
    except RuntimeError:
        xml = ""
        if device.has_app_error():
            print("HUNGERSTATION_ANDROID_RECOVERY reason=focused-app-error action=restart-app")
            device.start_app()
            try:
                xml = device.dump()
            except RuntimeError:
                pass
        if not xml:
            recovered = _ai_recover(
                device,
                restaurant,
                phase="reach_restaurant_search_after_ui_dump_failure",
                ready=_has_search_input,
                initial_xml=xml,
            )
            if recovered is None:
                raise CollectionFailure(
                    "UI_HIERARCHY_UNAVAILABLE",
                    "Android did not return a readable HungerStation screen hierarchy.",
                )
            xml = recovered
    # When vision recovery is available, do not spend tens of seconds polling
    # an unknown layout before asking it to adapt. Known location/setup states
    # are still handled locally without API cost.
    startup_checks = 4 if config.AI_NAVIGATION_ENABLED else 10
    for _ in range(startup_checks):
        if _has_android_app_error(xml):
            print("HUNGERSTATION_ANDROID_RECOVERY reason=app-error-dialog action=restart-app")
            device.start_app()
            time.sleep(3.0)
            xml = device.dump()
            continue
        location_setup = _find_location_setup_action(xml)
        if location_setup is not None:
            device.tap(*location_setup)
            time.sleep(2.5)
            xml = device.dump()
            continue
        if _has_search_input(xml):
            break
        location_recovery = _find_location_recovery(xml)
        if location_recovery is not None:
            device.tap(*location_recovery)
            time.sleep(2.5)
            xml = device.dump()
            continue
        if "com.google.android.apps.nexuslauncher" in xml:
            device.start_app()
        else:
            # An unknown hierarchy during startup is normally the native-to-
            # Flutter transition. Pressing Back here cancels that transition
            # and can leave the app without a focused window. Wait for an
            # identifiable state; Claude can choose Back later when visual
            # evidence shows a real modal or wrong screen.
            time.sleep(2.0)
            xml = device.dump()
            if _has_search_input(xml):
                break
        time.sleep(1.0)
        xml = device.dump()
    if not _has_search_input(xml):
        recovered = _ai_recover(
            device,
            restaurant,
            phase="reach_restaurant_search",
            ready=_has_search_input,
            initial_xml=xml,
        )
        if recovered is None:
            raise CollectionFailure(
                "SEARCH_SCREEN_UNREACHABLE",
                "HungerStation did not reach the restaurant search screen.",
            )
        xml = recovered

    point = _find_search_input(xml)
    if point is None:
        raise CollectionFailure(
            "SEARCH_INPUT_NOT_FOUND",
            "The HungerStation search field was not available on the current screen.",
        )
    device.tap(*point)
    time.sleep(1.5)
    xml = device.dump()
    transitioned_point = _find_search_input(xml)
    if transitioned_point is not None:
        device.tap(*transitioned_point)
    _replace_search_text(device, restaurant, submit=False)
    xml = device.dump()
    suggestion = _find_autocomplete_shortcut(xml, restaurant) or _find_search_suggestion(
        xml, restaurant
    )
    if suggestion:
        device.tap(*suggestion)
    else:
        device.key("66")
    result: tuple[int, int, str] | None = None
    search_shortcut_tapped = False
    result_checks = 4 if config.AI_NAVIGATION_ENABLED else 10
    for _ in range(result_checks):
        time.sleep(1.2)
        xml = device.dump()
        if _is_restaurant_menu(xml, restaurant):
            return restaurant.name
        result = _find_restaurant_result(xml, restaurant)
        if result is not None:
            break
        if not search_shortcut_tapped:
            shortcut = (
                _find_popular_search_shortcut(xml, restaurant)
                or _find_search_suggestion(xml, restaurant)
            )
            if shortcut is not None:
                device.tap(*shortcut)
                search_shortcut_tapped = True
    if result is None:
        result = _find_first_restaurant_card(xml, restaurant)
    if result is None:
        recovered = _ai_recover(
            device,
            restaurant,
            phase="find_and_open_restaurant_result",
            ready=lambda candidate: _is_restaurant_menu(candidate, restaurant),
            initial_xml=xml,
        )
        if recovered is not None:
            return restaurant.name
        raise CollectionFailure(
            "RESTAURANT_NOT_FOUND",
            f"{restaurant.name} was not found for the configured HungerStation location.",
        )
    device.tap(result[0], result[1])

    menu_checks = 4 if config.AI_NAVIGATION_ENABLED else 12
    for _ in range(menu_checks):
        time.sleep(0.8)
        xml = device.dump()
        if _is_restaurant_menu(xml, restaurant):
            return result[2]
    recovered = _ai_recover(
        device,
        restaurant,
        phase="recover_after_opening_restaurant_result",
        ready=lambda candidate: _is_restaurant_menu(candidate, restaurant),
        initial_xml=xml,
    )
    if recovered is not None:
        return result[2]
    raise CollectionFailure(
        "MENU_NOT_OPENED",
        f"HungerStation opened a result, but it did not resolve to the {restaurant.name} menu.",
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:12]


def parse_accessibility_label(label: str, brand_id: str, resource_id: str = "") -> dict[str, Any] | None:
    parts = [part.strip() for part in label.splitlines() if part.strip()]
    if not parts or "Min. Order" in parts or "more to place your order" in label:
        return None
    try:
        currency_at = next(index for index, part in enumerate(parts) if part in CURRENCY_LABELS)
    except StopIteration:
        return None
    if currency_at < 1 or currency_at + 1 >= len(parts):
        return None
    try:
        current_price = float(parts[currency_at + 1].replace(",", ""))
    except ValueError:
        return None
    if current_price < 0:
        return None

    metadata = re.compile(r"^(?:\d+(?:\.\d+)?%|\d+\+? orders|Bestseller|Top Rated)$", re.I)
    pre_price = parts[:currency_at]
    name = next((part for part in pre_price if not metadata.match(part)), None)
    if not name:
        return None
    description_parts = [
        part for part in pre_price
        if part != name and not metadata.match(part) and part.casefold() != "description undefined"
    ]
    calorie_text = next((part for part in description_parts if re.fullmatch(r"[\d,]+\s*kcal", part, re.I)), None)
    calories = int(re.sub(r"\D", "", calorie_text)) if calorie_text else None
    description = " ".join(part for part in description_parts if part != calorie_text) or None
    original_price = None
    for index in range(currency_at + 2, len(parts) - 1):
        if parts[index] in CURRENCY_LABELS:
            try:
                original_price = float(parts[index + 1].replace(",", ""))
            except ValueError:
                pass
            break
    discount_text = next((part for part in parts if re.fullmatch(r"\d+(?:\.\d+)?%", part)), None)
    discount = float(discount_text.rstrip("%")) if discount_text else None
    return {
        "source_product_id": f"HUNGERSTATION|{brand_id}|{_slug(name)}",
        "name_en": name,
        "description_en": description,
        "category_name_en": "HungerStation Menu",
        "currency": "SAR",
        "regular_price": original_price if original_price is not None else current_price,
        "special_price": current_price if original_price is not None else None,
        "effective_price": current_price,
        "discount_percentage": discount,
        "calories": calories,
        "availability": 1,
        "image_url": None,
        "raw_label": label,
        "is_summary_card": resource_id.startswith("gridMenuCell-"),
    }


def parse_split_accessibility_products(xml: str, brand_id: str) -> list[dict[str, Any]]:
    """Parse Flutter menu cards whose semantic labels are sibling nodes.

    HungerStation's newer menu UI exposes a clickable card rectangle followed
    by separate name, currency, current-price, and original-price nodes. The
    values are associated strictly by their bounds inside the same card; no AI
    is allowed to infer prices.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    nodes: list[tuple[ET.Element, tuple[int, int, int, int]]] = []
    for node in root.iter("node"):
        box = _bounds(node.attrib.get("bounds", ""))
        if box is not None:
            nodes.append((node, box))

    add_buttons = [
        box
        for node, box in nodes
        if node.attrib.get("resource-id", "").startswith("menuItemAction")
    ]
    card_boxes: list[tuple[int, int, int, int]] = []
    for node, box in nodes:
        width, height = box[2] - box[0], box[3] - box[1]
        if (
            node.attrib.get("clickable") != "true"
            or node.attrib.get("content-desc")
            or not (250 <= width <= 520 and 320 <= height <= 760)
        ):
            continue
        if any(
            box[0] <= (button[0] + button[2]) // 2 <= box[2]
            and box[1] <= (button[1] + button[3]) // 2 <= box[3]
            for button in add_buttons
        ):
            card_boxes.append(box)

    metadata = re.compile(r"^(?:\d+(?:\.\d+)?%|\d+\+? orders|Bestseller|Top Rated)$", re.I)
    numeric = re.compile(r"^\d+(?:,\d{3})*(?:\.\d+)?$")
    items: dict[str, dict[str, Any]] = {}
    for card in card_boxes:
        labelled: list[tuple[str, tuple[int, int, int, int]]] = []
        for node, box in nodes:
            label = (node.attrib.get("content-desc") or node.attrib.get("text") or "").strip()
            if not label:
                continue
            if box[0] < card[0] or box[1] < card[1] or box[2] > card[2] or box[3] > card[3]:
                continue
            labelled.append((label, box))

        price_pairs: list[tuple[float, tuple[int, int, int, int], int]] = []
        for label, currency_box in labelled:
            if label not in CURRENCY_LABELS:
                continue
            currency_center_y = (currency_box[1] + currency_box[3]) // 2
            values = []
            for candidate, value_box in labelled:
                if not numeric.fullmatch(candidate):
                    continue
                value_center_y = (value_box[1] + value_box[3]) // 2
                if value_box[0] >= currency_box[2] and abs(value_center_y - currency_center_y) <= 35:
                    values.append((value_box[0], candidate, value_box))
            if not values:
                continue
            _, value, value_box = min(values)
            try:
                price_pairs.append((float(value.replace(",", "")), value_box, currency_box[0]))
            except ValueError:
                continue
        if not price_pairs:
            continue
        price_pairs.sort(key=lambda pair: pair[2])
        current_price, current_box, _ = price_pairs[0]
        original_price = price_pairs[1][0] if len(price_pairs) > 1 else None

        name_candidates = []
        for label, box in labelled:
            if (
                label in CURRENCY_LABELS
                or numeric.fullmatch(label)
                or metadata.fullmatch(label)
                or "place your order" in label.casefold()
            ):
                continue
            if box[3] <= current_box[3] and box[1] < current_box[1]:
                name_candidates.append((box[1], label))
        if not name_candidates:
            continue
        _, name = max(name_candidates)
        discount_text = next(
            (label for label, _ in labelled if re.fullmatch(r"\d+(?:\.\d+)?%", label)),
            None,
        )
        discount = float(discount_text.rstrip("%")) if discount_text else None
        source_id = f"HUNGERSTATION|{brand_id}|{_slug(name)}"
        items[source_id] = {
            "source_product_id": source_id,
            "name_en": name,
            "description_en": None,
            "category_name_en": "HungerStation Menu",
            "currency": "SAR",
            "regular_price": original_price if original_price is not None else current_price,
            "special_price": current_price if original_price is not None else None,
            "effective_price": current_price,
            "discount_percentage": discount,
            "calories": None,
            "availability": 1,
            "image_url": None,
            "raw_label": " | ".join(label for label, _ in labelled),
            "is_summary_card": True,
        }
    return sorted(items.values(), key=lambda item: item["name_en"].casefold())


def deduplicate(labels: Iterable[tuple[str, str]], brand_id: str) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for resource_id, label in labels:
        item = parse_accessibility_label(label, brand_id, resource_id)
        if item is None:
            continue
        key = item["source_product_id"]
        previous = items.get(key)
        if previous is None or (previous["is_summary_card"] and not item["is_summary_card"]):
            items[key] = item
    return sorted(items.values(), key=lambda item: item["name_en"].casefold())


def product_image_candidates(
    xml: str,
    brand_id: str,
) -> list[tuple[str, str, tuple[int, int, int, int], int]]:
    """Find the largest product ImageView inside each accessible menu card."""
    root = ET.fromstring(xml)
    candidates: dict[str, tuple[str, str, tuple[int, int, int, int], int]] = {}
    for node in root.iter("node"):
        label = (node.attrib.get("content-desc") or "").strip()
        if not label:
            continue
        item = parse_accessibility_label(label, brand_id, node.attrib.get("resource-id", ""))
        if item is None:
            continue
        image_boxes: list[tuple[int, tuple[int, int, int, int]]] = []
        for child in node.iter("node"):
            if child.attrib.get("class") != "android.widget.ImageView":
                continue
            box = _bounds(child.attrib.get("bounds", ""))
            if box is None:
                continue
            width = box[2] - box[0]
            height = box[3] - box[1]
            if width < 120 or height < 100:
                continue
            image_boxes.append((width * height, box))
        if not image_boxes:
            continue
        area, box = max(image_boxes, key=lambda candidate: candidate[0])
        source_id = item["source_product_id"]
        candidate = (source_id, item["name_en"], box, area)
        previous = candidates.get(source_id)
        if previous is None or area > previous[3]:
            candidates[source_id] = candidate
    return list(candidates.values())


def save_product_images(
    screenshot_bytes: bytes,
    candidates: Iterable[tuple[str, str, tuple[int, int, int, int], int]],
    brand_id: str,
    image_scores: dict[str, int],
    *,
    image_dir: Path = config.IMAGE_DIR,
) -> dict[str, str]:
    """Crop product artwork from a menu screenshot and return public image URLs."""
    output: dict[str, str] = {}
    destination = image_dir / brand_id
    destination.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(screenshot_bytes)) as opened:
        screenshot = opened.convert("RGB")
    screen_width, screen_height = screenshot.size
    for source_id, product_name, box, area in candidates:
        x1, y1, x2, y2 = box
        if (
            area <= image_scores.get(source_id, 0)
            or x1 < 0
            or y1 < 80
            or x2 > screen_width
            or y2 > screen_height - 100
            or x2 <= x1
            or y2 <= y1
        ):
            continue
        filename = f"{_slug(product_name)}.jpg"
        image_path = destination / filename
        screenshot.crop(box).save(image_path, format="JPEG", quality=86, optimize=True)
        image_scores[source_id] = area
        output[source_id] = f"/hungerstation-images/{brand_id}/{filename}"
    return output


def collect_menu(device: AndroidDevice, brand_id: str, *, max_pages: int = 45) -> tuple[list[dict[str, Any]], list[list[str]]]:
    width, height = device.screen_size()
    center = width // 2
    top = max(1, int(height * 0.25))
    bottom = min(height - 1, int(height * 0.80))
    for _ in range(8):
        device.swipe(center, top, center, bottom, 350)
    pages: list[list[str]] = []
    labels: list[tuple[str, str]] = []
    split_items: dict[str, dict[str, Any]] = {}
    image_scores: dict[str, int] = {}
    image_urls: dict[str, str] = {}
    previous_signature = ""
    repeated = 0
    for _ in range(max_pages):
        xml = device.dump()
        if not _is_active_menu_page(xml, brand_id):
            restaurant = config.RESTAURANT_BY_ID[brand_id]
            menu_search_close = _find_menu_search_close(xml)
            if menu_search_close is not None:
                print(
                    f"HUNGERSTATION_ANDROID_RECOVERY brand={brand_id} "
                    "reason=menu-search-overlay action=close"
                )
                device.tap(*menu_search_close)
                time.sleep(1.0)
                xml = device.dump()
            if not _is_active_menu_page(xml, brand_id):
                recovered = _ai_recover(
                    device,
                    restaurant,
                    phase="return_to_menu_during_collection",
                    ready=lambda candidate: _is_active_menu_page(candidate, brand_id),
                    initial_xml=xml,
                )
                if recovered is None:
                    raise CollectionFailure(
                        "MENU_CLOSED_DURING_COLLECTION",
                        f"{restaurant.name} menu closed before collection completed.",
                    )
                xml = recovered
        page_labels = _labels(ET.fromstring(xml))
        page_split_items = parse_split_accessibility_products(xml, brand_id)
        for item in page_split_items:
            split_items[item["source_product_id"]] = item
        labels.extend(page_labels)
        pages.append([label for _, label in page_labels])
        try:
            candidates = product_image_candidates(xml, brand_id)
            uncaptured = []
            for source_id, product_name, box, area in candidates:
                filename = f"{_slug(product_name)}.jpg"
                existing = config.IMAGE_DIR / brand_id / filename
                if existing.exists():
                    image_urls[source_id] = f"/hungerstation-images/{brand_id}/{filename}"
                    image_scores[source_id] = max(area, image_scores.get(source_id, 0))
                else:
                    uncaptured.append((source_id, product_name, box, area))
            if uncaptured:
                image_urls.update(
                    save_product_images(
                        device.screenshot(),
                        uncaptured,
                        brand_id,
                        image_scores,
                    )
                )
        except Exception as error:
            print(f"HUNGERSTATION_IMAGE_WARNING brand={brand_id} message={error}")
        signature = "|".join(item["source_product_id"] for item in page_split_items)
        if not signature:
            signature = "|".join(
                label
                for resource_id, label in page_labels
                if resource_id.startswith("gridMenuCell-") or "\n§\n" in label
            )
        repeated = repeated + 1 if signature and signature == previous_signature else 0
        if repeated >= 2:
            break
        previous_signature = signature
        device.swipe(center, bottom, center, top, 600)
    items_by_source = {item["source_product_id"]: item for item in deduplicate(labels, brand_id)}
    for source_id, item in split_items.items():
        items_by_source.setdefault(source_id, item)
    items = sorted(items_by_source.values(), key=lambda item: item["name_en"].casefold())
    for item in items:
        source_id = item["source_product_id"]
        image_url = image_urls.get(source_id)
        if image_url is None:
            filename = f"{_slug(item['name_en'])}.jpg"
            if (config.IMAGE_DIR / brand_id / filename).exists():
                image_url = f"/hungerstation-images/{brand_id}/{filename}"
        item["image_url"] = image_url
    return items, pages


def load_capture(path: Path, brand_id: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    captured_items = payload.get("items", [])
    if captured_items:
        items_by_source: dict[str, dict[str, Any]] = {}
        for item in captured_items:
            source_id = item.get("source_product_id")
            if not source_id:
                continue
            previous = items_by_source.get(source_id)
            if previous is None or (
                previous.get("is_summary_card") and not item.get("is_summary_card")
            ):
                items_by_source[source_id] = item
        return sorted(
            items_by_source.values(),
            key=lambda item: item.get("name_en", "").casefold(),
        )
    labels: list[tuple[str, str]] = []
    for page in payload.get("pages", []):
        descriptions = page.get("descriptions", []) if isinstance(page, dict) else page
        labels.extend(("", label) for label in descriptions)
    if not labels:
        for item in payload.get("items", []):
            label = item.get("raw_accessibility_label") or item.get("raw_label")
            if label:
                labels.append((item.get("source_id", ""), label))
    return deduplicate(labels, brand_id)


def _capture_failure_evidence(
    device: AndroidDevice,
    restaurant: Restaurant,
    run_id: str,
) -> str | None:
    """Persist one bounded screen snapshot so UI changes are diagnosable."""
    destination = config.RAW_DIR / restaurant.id / "failures" / run_id
    saved = False
    try:
        destination.mkdir(parents=True, exist_ok=True)
        device.run(
            "shell", "uiautomator", "dump",
            "/data/local/tmp/hungerstation-failure.xml",
            attempts=1,
        )
        xml = device.run(
            "exec-out", "cat", "/data/local/tmp/hungerstation-failure.xml",
            attempts=1,
        )
        if xml.strip():
            (destination / "screen.xml").write_text(xml, encoding="utf-8")
            saved = True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        screenshot = device.run_bytes("exec-out", "screencap", "-p", attempts=1)
        if screenshot:
            (destination / "screen.png").write_bytes(screenshot)
            saved = True
    except (OSError, subprocess.SubprocessError):
        pass
    if saved:
        print(
            f"HUNGERSTATION_FAILURE_ARTIFACTS brand={restaurant.id} "
            f"path={destination}"
        )
        return str(destination)
    return None


def _failure_details(error: Exception) -> tuple[str, str]:
    """Translate internal exceptions into stable, actionable UI diagnostics."""
    if isinstance(error, CollectionFailure):
        return error.code, error.user_message
    if isinstance(error, subprocess.TimeoutExpired):
        return (
            "ADB_COMMAND_TIMEOUT",
            "The Android emulator did not answer an ADB command before the timeout.",
        )
    if isinstance(error, subprocess.CalledProcessError):
        command = [str(part) for part in (error.cmd or [])]
        raw_detail = getattr(error, "stderr", "") or getattr(error, "stdout", "") or ""
        detail = " ".join(str(raw_detail).split())[:240]
        lowered = detail.casefold()
        if "offline" in lowered:
            return "ADB_DEVICE_OFFLINE", "The Android emulator is connected but offline."
        if "unauthorized" in lowered:
            return "ADB_DEVICE_UNAUTHORIZED", "ADB is not authorized to control the Android emulator."
        if "not found" in lowered or "no devices" in lowered:
            return "ADB_DEVICE_NOT_FOUND", "The configured Android emulator was not found by ADB."
        if command[-3:-1] == ["geo", "fix"] or "geo" in command and "fix" in command:
            message = "ADB could not set the configured Riyadh location on the Android emulator."
            return "ADB_LOCATION_FAILED", f"{message} {detail}".strip()
        action = " ".join(command[3:7]) if len(command) > 3 else "unknown command"
        message = f"ADB command failed while running: {action}."
        return "ADB_COMMAND_FAILED", f"{message} {detail}".strip()
    if isinstance(error, FileNotFoundError):
        return "ADB_NOT_INSTALLED", "ADB could not be found in the configured Android SDK."
    message = " ".join(str(error).split())[:500]
    if "not ready" in message and "emulator" in message:
        return "ADB_DEVICE_NOT_READY", message
    if "incomplete UI hierarchy" in message:
        return "UI_HIERARCHY_UNAVAILABLE", message
    return "COLLECTION_FAILED", message or type(error).__name__


def collect_restaurant(
    restaurant: Restaurant,
    *,
    device: AndroidDevice,
    db_path: Path = config.DB_PATH,
    batch_id: str | None = None,
    from_capture: Path | None = None,
) -> dict[str, Any]:
    started_at = utc_now()
    run_id = f"hs-{restaurant.id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    try:
        resolved_name = restaurant.name
        if from_capture:
            items = load_capture(from_capture, restaurant.id)
            pages: list[list[str]] = []
        else:
            resolved_name = open_restaurant(device, restaurant)
            items, pages = collect_menu(device, restaurant.id)
        items_by_source: dict[str, dict[str, Any]] = {}
        for item in items:
            source_id = item["source_product_id"]
            previous = items_by_source.get(source_id)
            if previous is None or (
                previous.get("is_summary_card") and not item.get("is_summary_card")
            ):
                items_by_source[source_id] = item
        items = sorted(
            items_by_source.values(),
            key=lambda item: item.get("name_en", "").casefold(),
        )
        if len(items) < restaurant.minimum_products:
            raise CollectionFailure(
                "PRODUCT_COUNT_TOO_LOW",
                f"Only {len(items)} products were found for {restaurant.name}; expected at "
                f"least {restaurant.minimum_products}.",
            )
        finished_at = utc_now()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_path = config.RAW_DIR / restaurant.id / f"{stamp}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_payload = {
            "run_id": run_id,
            "batch_id": batch_id,
            "brand_id": restaurant.id,
            "restaurant": resolved_name,
            "collected_at": finished_at,
            "items": items,
            "pages": pages,
        }
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        database.save_success(
            run_id=run_id,
            batch_id=batch_id,
            brand_id=restaurant.id,
            restaurant_name=resolved_name,
            started_at=started_at,
            finished_at=finished_at,
            items=items,
            raw_capture_path=str(raw_path),
            path=db_path,
        )
        uploaded = upload(raw_payload)
        return {
            "brand_id": restaurant.id,
            "name": restaurant.name,
            "status": "success",
            "run_id": run_id,
            "product_count": len(items),
            "uploaded": uploaded,
        }
    except Exception as error:
        error_code, user_message = _failure_details(error)
        evidence_path = None
        if not from_capture:
            evidence_path = _capture_failure_evidence(device, restaurant, run_id)
        database.save_failure(
            run_id=run_id,
            batch_id=batch_id,
            brand_id=restaurant.id,
            restaurant_name=restaurant.name,
            started_at=started_at,
            finished_at=utc_now(),
            error=f"[{error_code}] {user_message}",
            path=db_path,
        )
        result = {
            "brand_id": restaurant.id,
            "name": restaurant.name,
            "status": "failed",
            "run_id": run_id,
            "product_count": 0,
            "error_code": error_code,
            "error": user_message,
        }
        if evidence_path:
            result["evidence_path"] = evidence_path
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--brand", choices=sorted(config.RESTAURANT_BY_ID))
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--serial", default=config.ADB_SERIAL)
    parser.add_argument("--adb")
    parser.add_argument("--db", type=Path, default=config.DB_PATH)
    parser.add_argument("--batch-id", default=os.environ.get("PULL_RUN_ID"))
    parser.add_argument("--from-capture", type=Path)
    args = parser.parse_args()

    database.init_db(args.db)
    device = AndroidDevice(find_adb(args.adb), args.serial)
    restaurants = config.RESTAURANTS if args.all else (config.RESTAURANT_BY_ID[args.brand],)
    results = []
    for restaurant in restaurants:
        result = collect_restaurant(
            restaurant,
            device=device,
            db_path=args.db,
            batch_id=args.batch_id,
            from_capture=args.from_capture,
        )
        results.append(result)
        print(
            f"HUNGERSTATION_RESULT brand={restaurant.id} status={result['status'].upper()} "
            f"products={result['product_count']}"
        )
        if result.get("error"):
            print(
                f"HUNGERSTATION_ERROR brand={restaurant.id} "
                f"code={result['error_code']} message={result['error']}"
            )
    print(json.dumps({"results": results}, ensure_ascii=False))
    return 0 if all(result["status"] == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
