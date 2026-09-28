"""
backend/excel_exporter.py
---------------------------------------------------------------------
Builds the three Excel workbooks the spec asks for, using openpyxl
directly (not pandas.to_excel) so headers/freeze panes/column widths can be
controlled precisely:

  exports/KFC_Daily_Changes_YYYY-MM-DD.xlsx
  exports/KFC_Monthly_Comparison_YYYY-MM.xlsx
  exports/KFC_Current_Catalog_YYYY-MM-DD.xlsx

Every export reads directly from SQLite - it never talks to the collector
or the live site. Pickup and Delivery are always separate worksheets (see
README "Do not create a primary pricing table that mixes Pickup and
Delivery values").
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from competitors.kfc.backend import config, database

HEADER_FILL = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)


def _write_sheet(wb: Workbook, title: str, headers: list[str], rows: list[list[Any]], *, first: bool = False) -> Worksheet:
    ws = wb.active if first and wb.active.title == "Sheet" else wb.create_sheet(title=title[:31])
    ws.title = title[:31]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            ws.cell(row=r, column=c, value=value)
    ws.freeze_panes = "A2"
    for col in range(1, len(headers) + 1):
        max_len = max([len(str(headers[col - 1]))] + [len(str(row[col - 1])) for row in rows if col - 1 < len(row)] or [10])
        ws.column_dimensions[get_column_letter(col)].width = min(max(max_len + 2, 10), 60)
    return ws


def _json_list(text: Optional[str]) -> list[Any]:
    if not text:
        return []
    try:
        val = json.loads(text)
        return val if isinstance(val, list) else [val]
    except (TypeError, json.JSONDecodeError):
        return [text]


def _format_join_item(x: Any) -> str:
    """Renders one item of a joined list column for display. A plain
    string/number is shown as-is; a dict with a "title"/"name" key (e.g.
    a size variant option {"id": ..., "title": "Medium", "isSelected": 1})
    is rendered as just its title/name instead of Python's raw dict repr,
    which read as garbage/unreadable text in this column."""
    if isinstance(x, dict):
        title = x.get("title") or x.get("name")
        price = x.get("price")
        if title and price is not None:
            return f"{title}: {price}"
        if title:
            return str(title)
    return str(x)


def _join(text: Optional[str]) -> str:
    return ", ".join(_format_join_item(x) for x in _json_list(text))


# --- Shared row builders -----------------------------------------------------

PRODUCT_HEADERS = [
    "Category", "Product", "Product ID", "Regular Price", "Special Price", "Effective Price",
    "Discount %", "Availability", "First Seen", "Last Seen", "Status", "Promo ID", "Image URL", "Source",
]


def _product_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> list[list[Any]]:
    query = """
        SELECT ps.*, p.first_seen_at, p.last_seen_at, p.status
        FROM product_snapshots ps
        JOIN products p ON p.canonical_product_key = ps.product_key
        WHERE ps.channel = ? AND ps.branch_id = ?
          AND ps.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = ps.channel AND cr.branch_id = ps.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY ps.category_name_en, ps.product_name_en
    """
    rows = conn.execute(query, (channel, branch_id)).fetchall()
    out = []
    for r in rows:
        out.append([
            r["category_name_en"], r["product_name_en"], r["product_id"], r["regular_price"], r["special_price"],
            r["effective_price"], r["discount_percentage"], "Available" if r["availability"] else "Unavailable",
            r["first_seen_at"], r["last_seen_at"], r["status"], r["promo_id"], r["image_url"], r["source_endpoint"],
        ])
    return out


OFFER_HEADERS = [
    "Offer Name", "Main Item", "Included Items", "Pieces", "Sides", "Drinks", "Sauces", "Sizes",
    "Original Price", "Offer Price", "Saving", "Discount %", "Offer Type", "First Seen", "Last Seen",
    "Status", "Screenshot",
]


def _offer_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> list[list[Any]]:
    query = """
        SELECT os.*, o.first_seen_at, o.last_seen_at, o.status
        FROM offer_snapshots os
        JOIN offers o ON o.offer_key = os.offer_key
        WHERE os.channel = ? AND os.branch_id = ?
          AND os.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = os.channel AND cr.branch_id = os.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY os.offer_name
    """
    rows = conn.execute(query, (channel, branch_id)).fetchall()
    out = []
    for r in rows:
        out.append([
            r["offer_name"], r["main_item"], _join(r["included_items"]), r["number_of_pieces"], _join(r["sides"]),
            _join(r["drinks"]), _join(r["sauces"]), _join(r["sizes"]), r["original_price"], r["offer_price"],
            r["saving_amount"], r["discount_percentage"], r["offer_type"], r["first_seen_at"], r["last_seen_at"],
            r["status"], r["screenshot_path"] or "",
        ])
    return out


CHANGE_HEADERS = ["Event Type", "Channel", "Entity Type", "Product / Offer", "Old Value", "New Value", "Absolute Change", "Percentage Change", "Detected At"]


def _change_rows(conn: sqlite3.Connection, run_ids: list[str]) -> list[list[Any]]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"SELECT * FROM change_events WHERE run_id IN ({placeholders}) ORDER BY detected_at",
        run_ids,
    ).fetchall()
    return [
        [r["event_type"], r["channel"], r["entity_type"], r["entity_name"], r["old_value"], r["new_value"], r["absolute_change"], r["percentage_change"], r["detected_at"]]
        for r in rows
    ]


NOT_OBSERVED_HEADERS = ["Type", "Channel", "Name", "Status Label", "Consecutive Missing Runs", "Last Seen"]


def _not_observed_rows(conn: sqlite3.Connection, branch_id: int) -> list[list[Any]]:
    out = []
    for r in conn.execute("SELECT * FROM products WHERE branch_id = ? AND status IN ('NOT_OBSERVED','REMOVED')", (branch_id,)):
        label = "Removed / Not observed for 3 successful runs" if r["status"] == "REMOVED" else f"Not observed ({r['consecutive_missing_count']} run(s))"
        out.append(["Product", r["channel"], r["product_name_en"], label, r["consecutive_missing_count"], r["last_seen_at"]])
    for r in conn.execute("SELECT * FROM offers WHERE branch_id = ? AND status IN ('NOT_OBSERVED','ENDED')", (branch_id,)):
        label = "Ended / Not observed for 3 successful runs" if r["status"] == "ENDED" else f"Not observed ({r['consecutive_missing_count']} run(s))"
        out.append(["Offer", r["channel"], r["offer_name"], label, r["consecutive_missing_count"], r["last_seen_at"]])
    return out


RUN_LOG_HEADERS = ["Run ID", "Date", "Channel", "Status", "Categories", "Products", "Offers", "Started At", "Finished At", "Error"]


def _run_log_rows(conn: sqlite3.Connection, branch_id: int, limit: int = 200) -> list[list[Any]]:
    rows = conn.execute(
        "SELECT * FROM crawl_runs WHERE branch_id = ? ORDER BY started_at DESC LIMIT ?",
        (branch_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        out.append([
            r["run_id"], (r["started_at"] or "")[:10], r["channel"], r["status"],
            f"{r['category_count']}/{r['expected_category_count']}", r["product_count"], r["offer_count"],
            r["started_at"], r["finished_at"], r["error_message"] or "",
        ])
    return out


SOURCES_HEADERS = ["Endpoint", "Method", "Path", "Last Verified At", "Last Run ID", "Last Status"]


def _sources_rows(conn: sqlite3.Connection) -> list[list[Any]]:
    rows = conn.execute("SELECT * FROM api_endpoints ORDER BY endpoint_name").fetchall()
    return [[r["endpoint_name"], r["method"], r["path"], r["last_verified_at"], r["last_run_id"], r["last_status"]] for r in rows]


def _latest_run(conn: sqlite3.Connection, channel: str, branch_id: int, on_or_before: Optional[str] = None) -> Optional[sqlite3.Row]:
    if on_or_before:
        return conn.execute(
            "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? AND status='SUCCESS' AND started_at <= ? ORDER BY started_at DESC LIMIT 1",
            (channel, branch_id, on_or_before),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? AND status='SUCCESS' ORDER BY started_at DESC LIMIT 1",
        (channel, branch_id),
    ).fetchone()


# --- Daily report ------------------------------------------------------------

def export_daily_report(conn: sqlite3.Connection, branch_id: int, report_date: Optional[date] = None) -> Path:
    report_date = report_date or date.today()
    wb = Workbook()

    day_str = report_date.strftime("%Y-%m-%d")
    day_end = day_str + "T23:59:59.999999Z"
    run_ids = []
    summary_rows = []
    for channel in config.CHANNELS:
        run = conn.execute(
            "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? AND started_at LIKE ? ORDER BY started_at DESC LIMIT 1",
            (channel, branch_id, f"{day_str}%"),
        ).fetchone()
        if run is None:
            run = _latest_run(conn, channel, branch_id, on_or_before=day_end)
        if run:
            run_ids.append(run["run_id"])
            summary_rows.append([channel, run["status"], run["category_count"], run["expected_category_count"], run["product_count"], run["offer_count"], run["started_at"], run["error_message"] or ""])
        else:
            summary_rows.append([channel, "NO RUN", 0, 0, 0, 0, None, "No run found for or before this date"])

    _write_sheet(wb, "Summary", ["Channel", "Status", "Categories Collected", "Expected Categories", "Products", "Offers", "Started At", "Error"], summary_rows, first=True)
    _write_sheet(wb, "Pickup Products", PRODUCT_HEADERS, _product_rows(conn, "PICKUP", branch_id))
    _write_sheet(wb, "Pickup Offers", OFFER_HEADERS, _offer_rows(conn, "PICKUP", branch_id))
    _write_sheet(wb, "Delivery Products", PRODUCT_HEADERS, _product_rows(conn, "DELIVERY", branch_id))
    _write_sheet(wb, "Delivery Offers", OFFER_HEADERS, _offer_rows(conn, "DELIVERY", branch_id))
    _write_sheet(wb, "Daily Changes", CHANGE_HEADERS, _change_rows(conn, run_ids))
    _write_sheet(wb, "Not Observed", NOT_OBSERVED_HEADERS, _not_observed_rows(conn, branch_id))
    _write_sheet(wb, "Sources and Run Metadata", SOURCES_HEADERS, _sources_rows(conn))

    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.EXPORTS_DIR / f"KFC_Daily_Changes_{day_str}.xlsx"
    wb.save(out_path)
    return out_path


# --- Monthly report -----------------------------------------------------------

def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    return start, end


def _latest_success_in_range(conn: sqlite3.Connection, channel: str, branch_id: int, start: str, end: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? AND status='SUCCESS' AND started_at >= ? AND started_at < ? ORDER BY started_at DESC LIMIT 1",
        (channel, branch_id, start, end),
    ).fetchone()


def _snapshot_dict(conn: sqlite3.Connection, run_id: Optional[str], table: str, key_col: str) -> dict[str, sqlite3.Row]:
    if not run_id:
        return {}
    rows = conn.execute(f"SELECT * FROM {table} WHERE run_id = ?", (run_id,)).fetchall()
    return {row[key_col]: row for row in rows}


def _monthly_channel_comparison(conn: sqlite3.Connection, channel: str, branch_id: int, cur_run: Optional[sqlite3.Row], prev_run: Optional[sqlite3.Row]) -> dict[str, Any]:
    cur_products = _snapshot_dict(conn, cur_run["run_id"] if cur_run else None, "product_snapshots", "product_key")
    prev_products = _snapshot_dict(conn, prev_run["run_id"] if prev_run else None, "product_snapshots", "product_key")
    cur_offers = _snapshot_dict(conn, cur_run["run_id"] if cur_run else None, "offer_snapshots", "offer_key")
    prev_offers = _snapshot_dict(conn, prev_run["run_id"] if prev_run else None, "offer_snapshots", "offer_key")

    new_products = [cur_products[k] for k in cur_products if k not in prev_products]
    removed_products = [prev_products[k] for k in prev_products if k not in cur_products]

    price_changes = []
    for k in set(cur_products) & set(prev_products):
        c, p = cur_products[k], prev_products[k]
        if c["regular_price"] is not None and p["regular_price"] is not None and float(c["regular_price"]) != float(p["regular_price"]):
            price_changes.append((c, p))

    new_offers = [cur_offers[k] for k in cur_offers if k not in prev_offers]
    ended_offers = [prev_offers[k] for k in prev_offers if k not in cur_offers]

    avg_pct_change = None
    pct_changes = []
    for c, p in price_changes:
        if p["regular_price"]:
            pct_changes.append((float(c["regular_price"]) - float(p["regular_price"])) / float(p["regular_price"]) * 100)
    if pct_changes:
        avg_pct_change = round(sum(pct_changes) / len(pct_changes), 2)

    return {
        "channel": channel,
        "current_run": cur_run, "previous_run": prev_run,
        "new_products": new_products, "removed_products": removed_products,
        "price_changes": price_changes, "new_offers": new_offers, "ended_offers": ended_offers,
        "avg_price_change_pct": avg_pct_change,
        "current_product_count": len(cur_products), "previous_product_count": len(prev_products),
    }


def export_monthly_report(conn: sqlite3.Connection, branch_id: int, year: int, month: int) -> Path:
    """Compares the latest SUCCESS snapshot in `year`-`month` against the
    latest SUCCESS snapshot in the previous calendar month, per channel -
    see README "Monthly Report". This is an independent, direct
    two-snapshot comparison (not a replay of stored daily change_events),
    since the two anchor runs are rarely adjacent successful runs."""
    start, end = _month_bounds(year, month)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_start, prev_end = _month_bounds(prev_year, prev_month)

    comparisons = {}
    for channel in config.CHANNELS:
        cur_run = _latest_success_in_range(conn, channel, branch_id, start, end)
        prev_run = _latest_success_in_range(conn, channel, branch_id, prev_start, prev_end)
        comparisons[channel] = _monthly_channel_comparison(conn, channel, branch_id, cur_run, prev_run)

    wb = Workbook()
    month_label = f"{year:04d}-{month:02d}"

    summary_rows = []
    for channel, c in comparisons.items():
        summary_rows.append([
            channel, c["current_run"]["run_id"] if c["current_run"] else "NO RUN",
            c["previous_run"]["run_id"] if c["previous_run"] else "NO RUN",
            len(c["new_products"]), len(c["new_offers"]), len(c["ended_offers"]), len(c["price_changes"]),
            c["avg_price_change_pct"], len(c["removed_products"]),
        ])
    _write_sheet(wb, "Monthly Summary", ["Channel", "Current Run", "Previous Run", "New Products", "New Offers", "Ended Offers", "Price Changes", "Avg Price Change %", "Removed Products"], summary_rows, first=True)

    for channel in config.CHANNELS:
        c = comparisons[channel]
        rows = []
        cur_map = _snapshot_dict(conn, c["current_run"]["run_id"] if c["current_run"] else None, "product_snapshots", "product_key")
        prev_map = _snapshot_dict(conn, c["previous_run"]["run_id"] if c["previous_run"] else None, "product_snapshots", "product_key")
        for key in set(cur_map) | set(prev_map):
            cur, prev = cur_map.get(key), prev_map.get(key)
            name = (cur or prev)["product_name_en"]
            rows.append([
                name, prev["regular_price"] if prev else None, cur["regular_price"] if cur else None,
                (cur["regular_price"] - prev["regular_price"]) if (cur and prev and cur["regular_price"] is not None and prev["regular_price"] is not None) else None,
                "Present" if cur else "Missing this month", "Present" if prev else "Missing last month",
            ])
        _write_sheet(wb, f"{channel.title()} Comparison", ["Product", "Previous Price", "Current Price", "Change", "This Month", "Last Month"], rows)

    new_product_rows = []
    for channel, c in comparisons.items():
        for r in c["new_products"]:
            new_product_rows.append([channel, r["product_name_en"], r["category_name_en"], r["regular_price"], r["effective_price"]])
    _write_sheet(wb, "New Products", ["Channel", "Product", "Category", "Regular Price", "Effective Price"], new_product_rows)

    new_offer_rows = []
    for channel, c in comparisons.items():
        for r in c["new_offers"]:
            new_offer_rows.append([channel, r["offer_name"], r["offer_type"], r["original_price"], r["offer_price"], r["discount_percentage"]])
    _write_sheet(wb, "New Offers", ["Channel", "Offer", "Type", "Original Price", "Offer Price", "Discount %"], new_offer_rows)

    ended_offer_rows = []
    for channel, c in comparisons.items():
        for r in c["ended_offers"]:
            ended_offer_rows.append([channel, r["offer_name"], r["offer_type"], r["original_price"], r["offer_price"]])
    _write_sheet(wb, "Ended Offers", ["Channel", "Offer", "Type", "Original Price", "Offer Price"], ended_offer_rows)

    price_change_rows = []
    for channel, c in comparisons.items():
        for cur, prev in c["price_changes"]:
            abs_change = round(float(cur["regular_price"]) - float(prev["regular_price"]), 2)
            pct = round(abs_change / float(prev["regular_price"]) * 100, 2) if prev["regular_price"] else None
            price_change_rows.append([channel, cur["product_name_en"], prev["regular_price"], cur["regular_price"], abs_change, pct])
    _write_sheet(wb, "Price Changes", ["Channel", "Product", "Previous Price", "Current Price", "Absolute Change", "Percentage Change"], price_change_rows)

    removed_returned_rows = []
    for channel, c in comparisons.items():
        for r in c["removed_products"]:
            removed_returned_rows.append([channel, "Removed", r["product_name_en"], r["category_name_en"]])
    _write_sheet(wb, "Removed and Returned", ["Channel", "Event", "Product", "Category"], removed_returned_rows)

    _write_sheet(wb, "Sources and Run Metadata", SOURCES_HEADERS, _sources_rows(conn))

    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.EXPORTS_DIR / f"KFC_Monthly_Comparison_{month_label}.xlsx"
    wb.save(out_path)
    return out_path


# --- Current full catalog -----------------------------------------------------

LEGACY_VIEW_HEADERS = ["Category", "Item", "Sandwich", "Regular", "Medium", "Large", "Source Link"]

_SIZE_TITLE_MAP = {"regular": "Regular", "medium": "Medium", "large": "Large"}


def _legacy_view_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> list[list[Any]]:
    """Mirrors the existing Competitors Pricing workbook shape (Category /
    Item / Sandwich / Regular / Medium / Large). Sizes come from
    variants[].options[] joined to items[].sel1Value prices when present
    (see normalizer.extract_sizes). If a size cannot be identified with
    confidence, that size column is left blank rather than guessed."""
    rows = []
    query = """
        SELECT ps.* FROM product_snapshots ps
        WHERE ps.channel = ? AND ps.branch_id = ?
          AND ps.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = ps.channel AND cr.branch_id = ps.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY ps.category_name_en, ps.product_name_en
    """
    for r in conn.execute(query, (channel, branch_id)):
        sizes = _json_list(r["sizes"])
        size_price = {"Regular": None, "Medium": None, "Large": None}
        if sizes:
            for s in sizes:
                if not isinstance(s, dict):
                    continue
                title = _SIZE_TITLE_MAP.get(str(s.get("title", "")).strip().lower())
                if not title:
                    continue
                if s.get("price") is not None:
                    size_price[title] = s.get("price")
                elif s.get("isSelected"):
                    # Fallback: only the selected size gets the card price
                    # when items[] did not supply a per-size price.
                    size_price[title] = r["effective_price"]
        rows.append([
            r["category_name_en"], r["product_name_en"], r["product_name_en"] if not sizes else "",
            size_price["Regular"], size_price["Medium"], size_price["Large"],
            r["product_url"] or r["image_url"] or "",
        ])
    return rows


NORMALIZED_HEADERS = [
    "Product ID", "Product", "Category", "Regular Price", "Special Price", "Effective Price",
    "Discount Amount", "Discount %", "Promo ID", "Limited Offer", "Availability", "Sizes",
    "Included Items", "Sides", "Drinks", "Sauces", "Add-ons", "Currency", "Image URL", "Source Link",
]


def _normalized_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> list[list[Any]]:
    query = """
        SELECT ps.* FROM product_snapshots ps
        WHERE ps.channel = ? AND ps.branch_id = ?
          AND ps.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = ps.channel AND cr.branch_id = ps.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY ps.category_name_en, ps.product_name_en
    """
    rows = []
    for r in conn.execute(query, (channel, branch_id)):
        rows.append([
            r["product_id"], r["product_name_en"], r["category_name_en"], r["regular_price"], r["special_price"],
            r["effective_price"], r["discount_amount"], r["discount_percentage"], r["promo_id"],
            "Yes" if r["limited_offer"] else "No", "Available" if r["availability"] else "Unavailable",
            _join(r["sizes"]), _join(r["included_items"]), _join(r["sides"]), _join(r["drinks"]),
            _join(r["sauces"]), _join(r["add_ons"]), r["currency"], r["image_url"] or "", r["product_url"] or r["image_url"] or "",
        ])
    return rows


def export_current_catalog(conn: sqlite3.Connection, branch_id: int, as_of: Optional[date] = None) -> Path:
    as_of = as_of or date.today()
    wb = Workbook()
    _write_sheet(wb, "Pickup Normalized", NORMALIZED_HEADERS, _normalized_rows(conn, "PICKUP", branch_id), first=True)
    _write_sheet(wb, "Pickup Legacy View", LEGACY_VIEW_HEADERS, _legacy_view_rows(conn, "PICKUP", branch_id))
    _write_sheet(wb, "Delivery Normalized", NORMALIZED_HEADERS, _normalized_rows(conn, "DELIVERY", branch_id))
    _write_sheet(wb, "Delivery Legacy View", LEGACY_VIEW_HEADERS, _legacy_view_rows(conn, "DELIVERY", branch_id))

    offer_rows = []
    for channel in config.CHANNELS:
        for row in _offer_rows(conn, channel, branch_id):
            offer_rows.append([channel] + row)
    _write_sheet(wb, "Offers", ["Channel"] + OFFER_HEADERS, offer_rows)

    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.EXPORTS_DIR / f"KFC_Current_Catalog_{as_of.strftime('%Y-%m-%d')}.xlsx"
    wb.save(out_path)
    return out_path
