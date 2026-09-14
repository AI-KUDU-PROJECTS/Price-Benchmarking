#!/usr/bin/env python3
"""
competitors/hardees/dashboard/page.py
---------------------------------------------------------------------
The Hardee's Streamlit dashboard. Mirrors competitors/kfc/dashboard/
page.py (and competitors/burger_king's, competitors/herfy's) layout and
data flow exactly - title + branch caption -> 5 top metrics -> 4 action
buttons -> 6 change-summary cards -> sidebar Filters -> tabs from
shared_ui.DASHBOARD_TAB_NAMES - now backed by the real SQLite collector
database (competitors/hardees/backend/database.py) instead of live guest-
session API calls.

REPLACES an earlier "live API preview" version of this file (see git
history / README.md "History of this competitor" - that version read
directly from competitors/hardees/api/client.py + services/* for a
research-phase-only preview, before the production collector existed).
That code is left in place under api/, services/, ui/, config/ for
reference but is no longer imported by this page - see README.md
"Superseded research-phase code".

Entry point (unchanged):

    from competitors.hardees.dashboard.page import render
    render()
---------------------------------------------------------------------
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import pytz
import streamlit as st

from shared_ui import (
    CHANNEL_COMPARE_COLUMNS,
    DASHBOARD_TAB_NAMES,
    OFFER_PRICE_COLUMNS,
    PRODUCT_PRICE_COLUMNS,
    expand_size_price_columns,
    format_run_timestamp,
    localize_timestamp_columns,
    order_columns,
)

from competitors.hardees.backend import config, database, excel_exporter, models, run_service

TZ = pytz.timezone(config.TIMEZONE)


# --- Data access -------------------------------------------------------------

@st.cache_resource
def _get_raw_connection() -> sqlite3.Connection:
    database.init_db()
    return sqlite3.connect(str(config.DB_PATH), check_same_thread=False)


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, _get_raw_connection(), params=params)


def latest_run(channel: str) -> pd.Series | None:
    df = query_df(
        "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? ORDER BY started_at DESC LIMIT 1",
        (channel, config.BRANCH_STORE_ID),
    )
    return df.iloc[0] if not df.empty else None


def latest_successful_run(channel: str) -> pd.Series | None:
    df = query_df(
        "SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? AND status='SUCCESS' ORDER BY started_at DESC LIMIT 1",
        (channel, config.BRANCH_STORE_ID),
    )
    return df.iloc[0] if not df.empty else None


def next_scheduled_run() -> datetime:
    try:
        hh, mm = (int(x) for x in config.DAILY_RUN_TIME.split(":"))
    except ValueError:
        hh, mm = 7, 0
    now = datetime.now(TZ)
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def products_df(channel: str) -> pd.DataFrame:
    df = query_df(
        """
        SELECT ps.*, p.first_seen_at, p.last_seen_at, p.status AS entity_status
        FROM product_snapshots ps
        JOIN products p ON p.canonical_product_key = ps.product_key
        WHERE ps.channel = ? AND ps.branch_id = ?
          AND ps.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = ps.channel AND cr.branch_id = ps.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY ps.category_name_en, ps.product_name_en
        """,
        (channel, config.BRANCH_STORE_ID),
    )
    if not df.empty and "sizes" in df.columns:
        # Expand Small/Regular/Medium/Large price columns, then keep a
        # compact "Regular: .. | Medium: .." summary in `sizes`.
        df = expand_size_price_columns(df)
    return df


def offers_df(channel: str) -> pd.DataFrame:
    df = query_df(
        """
        SELECT os.*, o.first_seen_at, o.last_seen_at, o.status AS entity_status
        FROM offer_snapshots os
        JOIN offers o ON o.offer_key = os.offer_key
        WHERE os.channel = ? AND os.branch_id = ?
          AND os.run_id = (
              SELECT cr.run_id FROM crawl_runs cr
              WHERE cr.channel = os.channel AND cr.branch_id = os.branch_id AND cr.status = 'SUCCESS'
              ORDER BY cr.started_at DESC LIMIT 1
          )
        ORDER BY os.offer_name
        """,
        (channel, config.BRANCH_STORE_ID),
    )
    if not df.empty and "sizes" in df.columns:
        df = expand_size_price_columns(df)
    return df


def change_events_df(limit: int = 5000) -> pd.DataFrame:
    return query_df(
        "SELECT * FROM change_events WHERE branch_id = ? ORDER BY detected_at DESC LIMIT ?",
        (config.BRANCH_STORE_ID, limit),
    )


def run_logs_df(limit: int = 300) -> pd.DataFrame:
    return query_df(
        "SELECT * FROM crawl_runs WHERE branch_id = ? ORDER BY started_at DESC LIMIT ?",
        (config.BRANCH_STORE_ID, limit),
    )


def today_change_summary() -> dict[str, int]:
    events = change_events_df(limit=20000)
    if events.empty:
        return {k: 0 for k in ("new_products", "new_offers", "price_increases", "price_decreases", "offers_ended", "not_observed")}
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    # detected_at is stored in UTC - compare against the dashboard timezone's date.
    local_dates = events["detected_at"].apply(
        lambda v: format_run_timestamp(v, config.TIMEZONE)[:10] if pd.notna(v) else ""
    )
    todays = events[local_dates == today_str]
    subset = todays if not todays.empty else events  # fall back to most recent events if no run happened today yet
    counts = subset["event_type"].value_counts()
    return {
        "new_products": int(counts.get(models.EVENT_NEW_PRODUCT, 0) + counts.get(models.EVENT_NEW_IN_CHANNEL, 0)),
        "new_offers": int(counts.get(models.EVENT_NEW_OFFER, 0)),
        "price_increases": int(counts.get(models.EVENT_PRICE_INCREASE, 0)),
        "price_decreases": int(counts.get(models.EVENT_PRICE_DECREASE, 0)),
        "offers_ended": int(counts.get(models.EVENT_OFFER_ENDED, 0)),
        "not_observed": int(counts.get(models.EVENT_PRODUCT_NOT_OBSERVED, 0) + counts.get(models.EVENT_OFFER_NOT_OBSERVED, 0)),
    }


def price_history_df(product_key: str) -> pd.DataFrame:
    return query_df(
        """
        SELECT ps.captured_at, ps.regular_price, ps.special_price, ps.channel, cr.status
        FROM product_snapshots ps
        JOIN crawl_runs cr ON cr.run_id = ps.run_id
        WHERE ps.product_key = ? AND cr.status = 'SUCCESS'
        ORDER BY ps.captured_at
        """,
        (product_key,),
    )


def refresh() -> None:
    st.cache_data.clear()


def pickup_vs_delivery_df() -> pd.DataFrame:
    """Side-by-side Pickup vs Delivery prices for the same product_id."""
    pickup = products_df("PICKUP")
    delivery = products_df("DELIVERY")
    if pickup.empty and delivery.empty:
        return pd.DataFrame()

    price_cols = ("effective_price", "regular_price", "special_price", "promo_id")
    shared_cols = (
        "product_id", "product_name_en", "normalized_name", "category_name_en",
        "description_en", "included_items", "sizes", "product_type",
        "currency", "image_url",
    )
    keep = list(shared_cols) + list(price_cols)
    p = pickup[[c for c in keep if c in pickup.columns]].copy()
    d = delivery[[c for c in keep if c in delivery.columns]].copy()

    def _rename_prices(df: pd.DataFrame, side: str) -> pd.DataFrame:
        return df.rename(columns={c: f"{c}_{side}" for c in price_cols if c in df.columns})

    if p.empty:
        d = _rename_prices(d, "delivery")
        for c in ("effective_price_pickup", "regular_price_pickup", "promo_id_pickup", "price_diff"):
            d[c] = None
        return order_columns(d, CHANNEL_COMPARE_COLUMNS)
    if d.empty:
        p = _rename_prices(p, "pickup")
        for c in ("effective_price_delivery", "regular_price_delivery", "promo_id_delivery", "price_diff"):
            p[c] = None
        return order_columns(p, CHANNEL_COMPARE_COLUMNS)

    p = _rename_prices(p, "pickup")
    d = _rename_prices(d, "delivery")
    merged = p.merge(d, on="product_id", how="outer", suffixes=("_pickup", "_delivery"))
    # Prefer non-null shared fields from either side.
    for base in shared_cols:
        if base == "product_id":
            continue
        left, right = f"{base}_pickup", f"{base}_delivery"
        if left in merged.columns and right in merged.columns:
            merged[base] = merged[left].fillna(merged[right])
            merged = merged.drop(columns=[left, right])
        elif left in merged.columns:
            merged = merged.rename(columns={left: base})
        elif right in merged.columns:
            merged = merged.rename(columns={right: base})
    ep = merged.get("effective_price_pickup")
    ed = merged.get("effective_price_delivery")
    if ep is not None and ed is not None:
        merged["price_diff"] = pd.to_numeric(ed, errors="coerce") - pd.to_numeric(ep, errors="coerce")
    else:
        merged["price_diff"] = None
    return order_columns(merged, CHANNEL_COMPARE_COLUMNS)


def render() -> None:
    """Renders the full Hardee's dashboard. Called by pages/2_Hardees.py."""
    st.set_page_config(page_title="Hardee's Price Intelligence", layout="wide")

    # --- Top section --------------------------------------------------------------

    st.title("Hardee's Price Intelligence")
    st.caption(f"Branch: {config.BRANCH_NAME} – {config.BRANCH_CITY}")

    top_cols = st.columns(5)
    pickup_run = latest_run("PICKUP")
    delivery_run = latest_run("DELIVERY")
    pickup_success = latest_successful_run("PICKUP")
    delivery_success = latest_successful_run("DELIVERY")

    with top_cols[0]:
        st.metric("Branch", f"{config.BRANCH_NAME}", config.BRANCH_CITY)
    with top_cols[1]:
        last_ok = max((r["started_at"] for r in (pickup_success, delivery_success) if r is not None), default=None)
        st.metric("Last Successful Run", format_run_timestamp(last_ok, config.TIMEZONE))
    with top_cols[2]:
        st.metric("Next Scheduled Run", next_scheduled_run().strftime("%Y-%m-%d %H:%M") if config.ENABLE_SCHEDULER else "Scheduler disabled")
    with top_cols[3]:
        st.metric("Pickup Status", pickup_run["status"] if pickup_run is not None else "No run yet")
    with top_cols[4]:
        st.metric("Delivery Status", delivery_run["status"] if delivery_run is not None else "No run yet")

    btn_cols = st.columns(4)
    with btn_cols[0]:
        run_clicked = st.button("▶ Run Now", type="primary", use_container_width=True)
    with btn_cols[1]:
        if st.button("\U0001f504 Refresh", use_container_width=True):
            refresh()
            st.rerun()
    with btn_cols[2]:
        export_daily_clicked = st.button("\U0001f4c4 Export Daily Excel", use_container_width=True)
    with btn_cols[3]:
        export_monthly_clicked = st.button("\U0001f4c4 Export Monthly Excel", use_container_width=True)

    if run_clicked:
        if run_service.is_run_active():
            st.warning("A collection run is already in progress. Please wait for it to finish before starting another.")
        else:
            with st.spinner("Running Pickup, then Delivery, then change detection... this can take a few minutes."):
                try:
                    summary = run_service.run_collection(channel="BOTH", trigger="MANUAL")
                    refresh()
                    if summary["overall_status"] == "SUCCESS":
                        st.success(f"Run complete: SUCCESS ({summary['batch_id']})")
                    elif summary["overall_status"] == "PARTIAL":
                        st.warning(f"Run complete: PARTIAL ({summary['batch_id']}) - see Run Logs for details")
                    else:
                        st.error(f"Run complete: FAILED ({summary['batch_id']}) - see Run Logs for details")
                    for ch in summary["channels"]:
                        st.write(f"**{ch['channel']}**: {ch['status']} - {ch.get('product_count', 0)} products, {ch.get('offer_count', 0)} offers")
                except run_service.RunAlreadyInProgressError as e:
                    st.warning(str(e))
            st.rerun()

    if export_daily_clicked:
        with database.get_connection() as conn:
            path = excel_exporter.export_daily_report(conn, config.BRANCH_STORE_ID)
        st.success(f"Daily Excel exported: {path.name}")
        with open(path, "rb") as f:
            st.download_button("Download Daily Excel", f.read(), file_name=path.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if export_monthly_clicked:
        today = date.today()
        with database.get_connection() as conn:
            path = excel_exporter.export_monthly_report(conn, config.BRANCH_STORE_ID, today.year, today.month)
        st.success(f"Monthly Excel exported: {path.name}")
        with open(path, "rb") as f:
            st.download_button("Download Monthly Excel", f.read(), file_name=path.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()

    # --- Summary cards -------------------------------------------------------------

    summary = today_change_summary()
    card_cols = st.columns(6)
    card_specs = [
        ("New Products", "new_products"), ("New Offers", "new_offers"),
        ("Price Increases", "price_increases"), ("Price Decreases", "price_decreases"),
        ("Offers Ended", "offers_ended"), ("Not Observed", "not_observed"),
    ]
    for col, (label, key) in zip(card_cols, card_specs):
        col.metric(label, summary[key])

    st.divider()

    # --- Sidebar filters (shared across price / change tabs) ---------------------

    st.sidebar.header("Filters")
    f_category = st.sidebar.text_input("Category contains")
    f_name_or_desc = st.sidebar.text_input("Name / description contains")
    f_offers_only = st.sidebar.checkbox("Offers Only")
    st.sidebar.divider()
    f_channel = st.sidebar.selectbox("Channel", ["All", "PICKUP", "DELIVERY"])
    f_status = st.sidebar.selectbox("Status", ["All", "ACTIVE", "NOT_OBSERVED", "REMOVED", "RETURNED", "ENDED"])
    f_event_type = st.sidebar.selectbox("Event Type", ["All"] + list(models.ALL_EVENT_TYPES))
    f_date = st.sidebar.date_input("Date", value=None)

    def apply_product_filters(df: pd.DataFrame) -> pd.DataFrame:
        out = df
        if f_status != "All" and "entity_status" in out.columns:
            out = out[out["entity_status"] == f_status]
        if f_category:
            out = out[out["category_name_en"].fillna("").str.contains(f_category, case=False)]
        if f_name_or_desc:
            name_hit = out["product_name_en"].fillna("").str.contains(f_name_or_desc, case=False)
            desc_hit = out["description_en"].fillna("").str.contains(f_name_or_desc, case=False) if "description_en" in out.columns else False
            out = out[name_hit | desc_hit]
        if f_offers_only:
            out = out[(out["special_price"].notna()) | (out["promo_id"].notna())]
        return order_columns(out, PRODUCT_PRICE_COLUMNS)

    def apply_offer_filters(df: pd.DataFrame) -> pd.DataFrame:
        out = df
        if f_category and "category_name_en" in out.columns:
            out = out[out["category_name_en"].fillna("").str.contains(f_category, case=False)]
        if f_name_or_desc:
            name_hit = out["offer_name"].fillna("").str.contains(f_name_or_desc, case=False) if "offer_name" in out.columns else False
            desc_hit = out["offer_description"].fillna("").str.contains(f_name_or_desc, case=False) if "offer_description" in out.columns else False
            out = out[name_hit | desc_hit]
        return order_columns(out, OFFER_PRICE_COLUMNS)

    def apply_event_filters(df: pd.DataFrame) -> pd.DataFrame:
        out = df
        if f_channel != "All":
            out = out[out["channel"] == f_channel]
        if f_event_type != "All":
            out = out[out["event_type"] == f_event_type]
        if f_date:
            out = out[out["detected_at"].str.startswith(str(f_date))]
        return out

    def render_offer_tab(channel: str, key_prefix: str) -> None:
        st.subheader(f"{channel.title()} Offers")
        df = apply_offer_filters(offers_df(channel))
        st.dataframe(df, use_container_width=True, hide_index=True)
        if df.empty:
            return
        selected = st.selectbox(
            "View full offer details",
            ["(select an offer)"] + df["offer_name"].fillna("(unnamed)").tolist(),
            key=f"{key_prefix}_offer_detail",
        )
        if selected != "(select an offer)":
            row = df[df["offer_name"] == selected].iloc[0]
            st.json(row.to_dict())
            if row.get("screenshot_path") and Path(str(row["screenshot_path"])).exists():
                st.image(str(row["screenshot_path"]), caption=selected)

    # --- Tabs (shared order across every competitor via DASHBOARD_TAB_NAMES) -----

    tabs = st.tabs(list(DASHBOARD_TAB_NAMES))

    with tabs[0]:
        st.subheader("Overview")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Pickup**")
            st.json({
                "status": pickup_run["status"] if pickup_run is not None else "No run yet",
                "products": int(pickup_run["product_count"]) if pickup_run is not None else 0,
                "offers": int(pickup_run["offer_count"]) if pickup_run is not None else 0,
                "categories": f"{int(pickup_run['category_count'])}/{int(pickup_run['expected_category_count'])}" if pickup_run is not None else "n/a",
                "error": pickup_run["error_message"] if pickup_run is not None else None,
            })
        with c2:
            st.write("**Delivery**")
            st.json({
                "status": delivery_run["status"] if delivery_run is not None else "No run yet",
                "products": int(delivery_run["product_count"]) if delivery_run is not None else 0,
                "offers": int(delivery_run["offer_count"]) if delivery_run is not None else 0,
                "categories": f"{int(delivery_run['category_count'])}/{int(delivery_run['expected_category_count'])}" if delivery_run is not None else "n/a",
                "error": delivery_run["error_message"] if delivery_run is not None else None,
            })
        st.write("Recent change events:")
        st.dataframe(change_events_df(limit=25), use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Pickup Prices")
        st.caption("Columns: category → name → normalized → prices → currency → description → included → size → type → image → channel.")
        st.dataframe(apply_product_filters(products_df("PICKUP")), use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("Delivery Prices")
        st.caption("Same columns as Pickup Prices for side-by-side reading.")
        st.dataframe(apply_product_filters(products_df("DELIVERY")), use_container_width=True, hide_index=True)

    with tabs[3]:
        render_offer_tab("PICKUP", "pickup")

    with tabs[4]:
        render_offer_tab("DELIVERY", "delivery")

    with tabs[5]:
        st.subheader("Pickup vs Delivery")
        st.caption("Same product_id across channels. `price_diff` = delivery effective_price − pickup effective_price.")
        cmp_df = pickup_vs_delivery_df()
        if f_category and not cmp_df.empty and "category_name_en" in cmp_df.columns:
            cmp_df = cmp_df[cmp_df["category_name_en"].fillna("").str.contains(f_category, case=False)]
        if f_name_or_desc and not cmp_df.empty:
            name_hit = cmp_df["product_name_en"].fillna("").str.contains(f_name_or_desc, case=False) if "product_name_en" in cmp_df.columns else False
            desc_hit = cmp_df["description_en"].fillna("").str.contains(f_name_or_desc, case=False) if "description_en" in cmp_df.columns else False
            cmp_df = cmp_df[name_hit | desc_hit]
        st.dataframe(order_columns(cmp_df, CHANNEL_COMPARE_COLUMNS), use_container_width=True, hide_index=True)

    with tabs[6]:
        st.subheader("Changes")
        events = apply_event_filters(change_events_df())

        def _color_for(event_type: str) -> str:
            return models.EVENT_COLOR_MAP.get(event_type, models.EVENT_COLOR_GRAY)

        if events.empty:
            st.info("No change events recorded yet - run a collection first.")
        else:
            display = events.copy()
            display["Color"] = display["event_type"].map(_color_for)
            st.dataframe(
                display[["event_type", "channel", "entity_name", "old_value", "new_value", "absolute_change", "percentage_change", "detected_at", "Color"]],
                use_container_width=True, hide_index=True,
            )

    with tabs[7]:
        st.subheader("History / Logs")
        hist_mode = st.radio("View", ["Price History", "Run Logs", "Monthly Comparison"], horizontal=True, key="hardees_history_mode")
        if hist_mode == "Price History":
            channel_choice = st.radio("Channel", ["PICKUP", "DELIVERY"], horizontal=True, key="hardees_hist_channel")
            prod_df = products_df(channel_choice)
            if prod_df.empty:
                st.info("No products collected yet for this channel.")
            else:
                product_choice = st.selectbox("Product", prod_df["product_name_en"].tolist(), key="hardees_hist_product")
                row = prod_df[prod_df["product_name_en"] == product_choice].iloc[0]
                hist = price_history_df(row["product_key"])
                if hist.empty:
                    st.info("No price history yet for this product.")
                else:
                    hist = hist.set_index("captured_at")[["regular_price", "special_price"]]
                    st.line_chart(hist)
                    st.dataframe(hist, use_container_width=True)
        elif hist_mode == "Run Logs":
            logs = run_logs_df()
            if f_channel != "All":
                logs = logs[logs["channel"] == f_channel]
            logs = localize_timestamp_columns(logs, ("started_at", "finished_at"), config.TIMEZONE)
            st.dataframe(logs, use_container_width=True, hide_index=True)
        else:
            today = date.today()
            month_choice = st.selectbox("Month", [today.strftime("%Y-%m"), (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")])
            year, month = (int(x) for x in month_choice.split("-"))
            if st.button("Generate Monthly Comparison"):
                with database.get_connection() as conn:
                    path = excel_exporter.export_monthly_report(conn, config.BRANCH_STORE_ID, year, month)
                st.success(f"Generated {path.name}")
                st.session_state["monthly_path"] = str(path)
            if "monthly_path" in st.session_state and Path(st.session_state["monthly_path"]).exists():
                xls = pd.ExcelFile(st.session_state["monthly_path"])
                sheet = st.selectbox("Sheet", xls.sheet_names)
                st.dataframe(xls.parse(sheet), use_container_width=True, hide_index=True)
