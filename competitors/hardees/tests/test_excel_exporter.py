"""
competitors/hardees/tests/test_excel_exporter.py
Covers required test #13: Excel generation.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from competitors.hardees.backend import config, excel_exporter
from competitors.hardees.tests.test_change_detector import bump_run, ingest


def test_daily_report_generates_all_required_worksheets(conn, tmp_path, monkeypatch, delivery_result, pickup_result):
    monkeypatch.setattr(config, "EXPORTS_DIR", tmp_path / "exports")
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    ingest(conn, tmp_path, "batch1", "PICKUP", bump_run(pickup_result, "2026-08-01"))

    path = excel_exporter.export_daily_report(conn, 24, date(2026, 8, 1))
    assert path.exists()
    wb = load_workbook(path)
    expected_sheets = {
        "Summary", "Pickup Products", "Pickup Offers", "Delivery Products",
        "Delivery Offers", "Daily Changes", "Not Observed", "Sources and Run Metadata",
    }
    assert expected_sheets.issubset(set(wb.sheetnames))
    # Delivery Products must have real rows (header + data), Pickup Products
    # sheet must exist even though this test only fed it PICKUP data too.
    assert wb["Delivery Products"].max_row > 1
    assert wb["Pickup Products"].max_row > 1


def test_monthly_report_generates_all_required_worksheets(conn, tmp_path, monkeypatch, delivery_result):
    monkeypatch.setattr(config, "EXPORTS_DIR", tmp_path / "exports")
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-07-15"))
    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(delivery_result, "2026-08-15"))

    path = excel_exporter.export_monthly_report(conn, 24, 2026, 8)
    assert path.exists()
    wb = load_workbook(path)
    expected_sheets = {
        "Monthly Summary", "Pickup Comparison", "Delivery Comparison", "New Products",
        "New Offers", "Ended Offers", "Price Changes", "Removed and Returned", "Sources and Run Metadata",
    }
    assert expected_sheets.issubset(set(wb.sheetnames))


def test_current_catalog_generates_all_required_worksheets(conn, tmp_path, monkeypatch, delivery_result, pickup_result):
    monkeypatch.setattr(config, "EXPORTS_DIR", tmp_path / "exports")
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    ingest(conn, tmp_path, "batch1", "PICKUP", bump_run(pickup_result, "2026-08-01"))

    path = excel_exporter.export_current_catalog(conn, 24, date(2026, 8, 1))
    assert path.exists()
    assert path.name.startswith("Hardees_Current_Catalog_")
    wb = load_workbook(path)
    expected_sheets = {"Pickup Normalized", "Pickup Legacy View", "Delivery Normalized", "Delivery Legacy View", "Offers"}
    assert expected_sheets.issubset(set(wb.sheetnames))

    # Legacy View must never fabricate a size - a product with no size
    # variant must show blank Regular/Medium/Large columns, not a guess.
    legacy_ws = wb["Delivery Legacy View"]
    header = [c.value for c in legacy_ws[1]]
    assert header == ["Category", "Item", "Sandwich", "Regular", "Medium", "Large", "Source Link"]

    # Regression: the Normalized sheet's "Sizes" column must render each
    # variant option with its joined items[] price when present
    # ("Medium: 32, Large: 37"), never Python's raw dict repr.
    normalized_ws = wb["Delivery Normalized"]
    norm_header = [c.value for c in normalized_ws[1]]
    norm_rows = {row[norm_header.index("Product")]: row for row in normalized_ws.iter_rows(min_row=2, values_only=True)}
    sizes_cell = norm_rows["Low Mein Thickburger Combo"][norm_header.index("Sizes")]
    assert sizes_cell == "Medium: 32.0, Large: 37.0"
    assert "{" not in sizes_cell and "'" not in sizes_cell

    # Legacy View fills EVERY size column from items[].sel1Value prices,
    # not only the selected size.
    legacy_rows = {row[1]: row for row in legacy_ws.iter_rows(min_row=2, values_only=True)}
    low_mein = legacy_rows["Low Mein Thickburger Combo"]
    assert low_mein[header.index("Medium")] == 32.0
    assert low_mein[header.index("Large")] == 37.0
    assert low_mein[header.index("Regular")] is None
