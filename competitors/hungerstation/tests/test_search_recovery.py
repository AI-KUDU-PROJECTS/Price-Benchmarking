"""Offline regressions for the Burger King / AlBaik failures of 2026-11-03."""
from __future__ import annotations

import pytest

from competitors.hungerstation import collector, config
from competitors.hungerstation.config import RESTAURANT_BY_ID

PACKAGE = collector.PACKAGE
HOME = f'''<hierarchy><node package="{PACKAGE}" class="android.widget.EditText"
    resource-id="{PACKAGE}:id/input_csc" enabled="true" focusable="false"
    bounds="[132,247][999,299]" /></hierarchy>'''
# The failed AlBaik capture has a focused field with no ID or description.
SEARCH = f'''<hierarchy><node package="{PACKAGE}" class="android.widget.EditText"
    resource-id="" text="{{text}}" enabled="true" focusable="true" focused="true"
    bounds="[265,113][1004,160]" />
    <node resource-id="UniversalSearch_popular_search_cell_0" text="burger" />
    </hierarchy>'''
LOCATION = f'''<hierarchy><node text="Select a delivery location" />
    <node resource-id="{PACKAGE}:id/confirm_drop_off_button" enabled="true"
    clickable="true" bounds="[42,2158][1038,2284]" /></hierarchy>'''


class OfflineDevice:
    """Only a local state machine; never invokes Android or a model API."""

    def __init__(self, brand: str, *, location: bool = False, accept_text: bool = True):
        self.restaurant = RESTAURANT_BY_ID[brand]
        self.state = "location" if location else "home"
        self.text = ""
        self.accept_text = accept_text
        self.typed: list[str] = []
        self.taps: list[tuple[int, int]] = []
        self.keys: list[str] = []

    def start_app(self):
        pass

    def has_app_error(self):
        return False

    def dump(self):
        if self.state == "location":
            return LOCATION
        if self.state == "home":
            return HOME
        if self.state == "menu":
            return (f'<hierarchy><node text="{self.restaurant.name}" bounds="[0,100][900,200]" />'
                    '<node text="Min. Order" /></hierarchy>')
        return SEARCH.format(text=self.text)

    def tap(self, x, y):
        self.taps.append((x, y))
        if self.state == "location":
            assert (x, y) == (540, 2221)
            self.state = "home"
        elif self.state == "home":
            assert (x, y) == (565, 273)
            self.state = "search"
        else:
            assert (x, y) == (634, 136)

    def run(self, *args):
        assert self.state == "search", "Typing must wait for the editable search page"
        if args[:3] == ("shell", "input", "text"):
            self.typed.append(args[3])
            if self.accept_text:
                self.text = args[3].replace("%s", " ")
        return ""

    def key(self, code):
        self.keys.append(code)
        if code == "66":
            assert self.text == self.restaurant.search_term
            self.state = "menu"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)


@pytest.mark.parametrize("brand", ["burger-king", "albaik"])
def test_open_restaurant_handles_unlabelled_flutter_search(brand):
    device = OfflineDevice(brand)
    assert collector.open_restaurant(device, device.restaurant) == device.restaurant.name
    assert device.typed == [device.restaurant.search_term.replace(" ", "%s")]
    assert device.state == "menu"


@pytest.mark.parametrize("brand,location", [("burger-king", True), ("albaik", False)])
def test_recovery_reaches_menu_from_recorded_failure_states(monkeypatch, brand, location):
    class NoVisionNeeded:
        available = True

        def choose_action(self, **kwargs):
            pytest.fail("Known search/location states should not require vision guesses")

    monkeypatch.setattr(config, "AI_NAVIGATION_ENABLED", True)
    monkeypatch.setattr(config, "AI_MAX_ACTIONS", 6)
    monkeypatch.setattr(collector, "AnthropicNavigator", NoVisionNeeded)
    device = OfflineDevice(brand, location=location)
    if not location:
        device.state = "search"
    result = collector._ai_recover(
        device, device.restaurant, phase="find_and_open_restaurant_result",
        ready=lambda xml: collector._is_restaurant_menu(xml, device.restaurant),
        initial_xml=device.dump(),
    )
    assert collector._is_restaurant_menu(result, device.restaurant)
    assert device.typed == [device.restaurant.search_term.replace(" ", "%s")]
    if location:
        assert device.taps[0] == (540, 2221)


def test_search_does_not_submit_when_typing_did_not_reach_field():
    device = OfflineDevice("albaik", accept_text=False)
    assert not collector._search_restaurant(device, device.restaurant, (565, 273))
    assert "66" not in device.keys
    assert device.state == "search"


def test_search_waits_for_native_to_flutter_transition():
    class SlowDevice(OfflineDevice):
        pending = 2

        def dump(self):
            if self.state == "search" and self.pending:
                self.pending -= 1
                return HOME
            return super().dump()

    device = SlowDevice("burger-king")
    assert collector._search_restaurant(device, device.restaurant, (565, 273))
    assert device.typed == ["burger%sking"]


def test_open_restaurant_accepts_already_open_target_menu():
    device = OfflineDevice("burger-king")
    device.state = "menu"
    assert collector.open_restaurant(device, device.restaurant) == "Burger King"
    assert device.taps == []
    assert device.typed == []


def test_search_accepts_direct_transition_to_target_menu():
    class DirectMenuDevice(OfflineDevice):
        def tap(self, x, y):
            self.state = "menu"

    device = DirectMenuDevice("burger-king")
    assert collector._search_restaurant(device, device.restaurant, (565, 273))
    assert device.typed == []


@pytest.mark.parametrize("xml", [
    HOME.replace('enabled="true"', 'enabled="false"'),
    SEARCH.format(text="").replace('enabled="true"', 'enabled="false"'),
    SEARCH.format(text="").replace('UniversalSearch_popular_search_cell_0', 'address_search'),
    SEARCH.format(text="").replace('UniversalSearch_popular_search_cell_0', 'phone_verification'),
    SEARCH.format(text="").replace('</hierarchy>', '<node resource-id="menuSearchInput" /></hierarchy>'),
    SEARCH.format(text="").replace(PACKAGE, 'another.app'),
    SEARCH.format(text="").replace('focusable="true"', 'focusable="false"'),
    SEARCH.format(text="").replace('focused="true"', 'password="true"'),
])
def test_search_rejects_disabled_unrelated_or_sensitive_inputs(xml):
    assert collector._find_search_input(xml) is None
    assert not collector._has_search_input(xml)


def test_search_rejects_ambiguous_editable_fields():
    extra = (f'<node package="{PACKAGE}" class="android.widget.EditText" focusable="true" '
             'bounds="[0,500][500,600]" />')
    xml = SEARCH.format(text="").replace('</hierarchy>', extra + '</hierarchy>')
    assert collector._find_search_input(xml) is None


def test_search_uses_editable_child_inside_flutter_search_wrapper():
    xml = f'''<hierarchy><node package="{PACKAGE}" class="android.widget.EditText"
        resource-id="UniversalSearch_search_bar_text_field" text="" focusable="true"
        enabled="true" bounds="[168,89][1059,184]">
        <node package="{PACKAGE}" class="android.widget.EditText" resource-id=""
        text="burger king" focusable="true" enabled="true" bounds="[265,113][941,160]" />
        </node><node resource-id="UniversalSearch_autocomplete_cell_0" /></hierarchy>'''
    assert collector._find_search_input(xml) == (603, 136)
    assert collector._find_search_node(xml).get("text") == "burger king"


class LongMenuDevice:
    def __init__(self, length):
        self.length = length
        self.page = 0

    def screen_size(self):
        return (1080, 2400)

    def swipe(self, *args):
        pass

    def dump(self):
        self.page += 1
        number = min(self.page, self.length)
        return (f'<hierarchy><node package="{PACKAGE}">'
                f'<node content-desc="Sandwich {number}&#10;§&#10;25" '
                'bounds="[0,600][1080,1000]" /></node></hierarchy>')


def test_long_menu_continues_beyond_old_limit_until_end():
    items, pages = collector.collect_menu(LongMenuDevice(50), "burger-king")
    assert len(items) == 50
    assert len(pages) == 52


def test_scroll_limit_does_not_return_incomplete_menu():
    with pytest.raises(collector.CollectionFailure) as error:
        collector.collect_menu(LongMenuDevice(50), "burger-king", max_pages=45)
    assert error.value.code == "MENU_SCROLL_LIMIT"
