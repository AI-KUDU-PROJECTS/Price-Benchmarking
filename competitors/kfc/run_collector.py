#!/usr/bin/env python3
"""
run_collector.py
---------------------------------------------------------------------
Manual/one-shot collection run. This is the same code path scheduler.py's
daily job and app.py's "Run Now" button use (backend.run_service.
run_collection) - there is exactly one way a collection run can start.

Usage:
    python run_collector.py                    # both channels
    python run_collector.py --channel=PICKUP
    python run_collector.py --channel=DELIVERY
    python run_collector.py --no-screenshots    # skip screenshot capture (faster manual test runs)
---------------------------------------------------------------------
"""
from __future__ import annotations

import argparse
import json
import sys

from competitors.kfc.backend import config, database, run_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one KFC price/offer collection pass.")
    parser.add_argument("--channel", default="BOTH", choices=["PICKUP", "DELIVERY", "BOTH"])
    parser.add_argument("--no-screenshots", action="store_true", help="Skip screenshot capture for NEW_PRODUCT/NEW_OFFER events")
    args = parser.parse_args()

    config.ensure_directories()
    database.init_db()

    print(f"[RUN] Starting collection (channel={args.channel}, branch={config.BRANCH_NAME} storeId={config.BRANCH_STORE_ID})")
    try:
        summary = run_service.run_collection(channel=args.channel, trigger="MANUAL", enable_screenshots=not args.no_screenshots)
    except run_service.RunAlreadyInProgressError as e:
        print(f"[RUN] Refused to start: {e}")
        return 2

    print(f"[RUN] Finished. Overall status: {summary['overall_status']}")
    for ch in summary["channels"]:
        print(f"  - {ch['channel']}: {ch['status']} (products={ch.get('product_count', 0)}, offers={ch.get('offer_count', 0)})")
        change = ch.get("change_summary")
        if isinstance(change, dict) and "products" in change:
            p, o = change["products"], change["offers"]
            print(f"      new_products={p['new_product']} price_up={p['price_increase']} price_down={p['price_decrease']} not_observed={p['not_observed']} removed={p['removed']} returned={p['returned']}")
            print(f"      new_offers={o['new_offer']} offer_changed={o['changed']} offer_not_observed={o['not_observed']} offer_ended={o['ended']} offer_returned={o['returned']}")
    print(f"[RUN] Screenshots captured: {summary['screenshots_captured']}")
    print(f"[RUN] Full summary JSON: {json.dumps(summary, default=str)}")
    return 0 if summary["overall_status"] != "FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
