import xml.etree.ElementTree as ET
import subprocess

import pytest

from competitors.albaik.collector.app import AlbaikDevice, Collector
from competitors.hungerstation.collector import CollectionFailure


def menu(y):
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", text="MENU", bounds=f"[118,{y}][242,{y+54}]")
    for i, name in enumerate(("Breakfast", "Chicken", "Seafood")):
        ET.SubElement(root, "node", **{"content-desc": name, "clickable": "true",
            "bounds": f"[{26+i*260},{y+107}][{263+i*260},{y+199}]"})
    return root


def test_category_discovery_hides_animated_banner_before_reading_again(tmp_path):
    class Device:
        banner_bottom = 1488
        def screen_size(self): return 1080, 2400
        def swipe(self, x1, y1, x2, y2, duration=500):
            if y1 != y2:
                assert y2 < y1
                self.banner_bottom -= 800
        def dump(self):
            if self.banner_bottom > 0:
                raise CollectionFailure("UI_UNAVAILABLE", "ERROR: could not get idle state.")
            return ET.tostring(menu(259), encoding="unicode")
    collector = Collector(Device(), "DELIVERY", tmp_path)
    collector.discover_categories(menu(2056))
    assert collector.categories == ["Breakfast", "Chicken", "Seafood"]


def test_category_selection_reveals_first_rows_without_returning_to_banner(tmp_path):
    class Device:
        tapped = False
        aligned = False
        def screen_size(self): return 1080, 2400
        def swipe(self, x1, y1, x2, y2, duration):
            assert self.tapped
            assert 0 < y2-y1 <= 240
            self.aligned = True
        def tap(self, x, y):
            assert 286 < x < 523 and 366 < y < 458
            self.tapped = True
        def dump(self): return ET.tostring(menu(350 if self.aligned else 259), encoding="unicode")
    device = Device()
    collector = Collector(device, "DELIVERY", tmp_path)
    collector.select_category(menu(259), "Chicken")
    assert device.tapped and device.aligned


def test_android_idle_failure_and_collection_stage_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr("competitors.albaik.collector.app.time.sleep", lambda _: None)
    device = AlbaikDevice(tmp_path / "adb", "test")
    calls = []
    def run(*args, **kwargs):
        if "uiautomator" in args:
            assert "2>&1" in args
            calls.append(args)
            return "ERROR: could not get idle state.\n"
        return ""
    monkeypatch.setattr(device, "run", run)
    monkeypatch.setattr(device, "screen_size", lambda: (1080, 2400))
    collector = Collector(device, "DELIVERY", tmp_path)
    with pytest.raises(CollectionFailure, match="Reading categories: ERROR: could not get idle state") as error:
        collector.screen("categories")
    assert error.value.code == "UI_UNAVAILABLE"
    assert len(calls) == 4


def test_timed_out_reader_keeps_diagnostic_output_instead_of_raising_type_error(tmp_path, monkeypatch):
    monkeypatch.setattr("competitors.albaik.collector.app.time.sleep", lambda _: None)
    device = AlbaikDevice(tmp_path / "adb", "test")
    def run(*args, **kwargs):
        if "uiautomator" in args:
            raise subprocess.TimeoutExpired(args, 15, output=b"Reader timed out\n")
        return ""
    monkeypatch.setattr(device, "run", run)
    with pytest.raises(CollectionFailure, match="Reader timed out") as error:
        device.dump()
    assert error.value.code == "UI_UNAVAILABLE"
