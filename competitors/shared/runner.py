"""One-shot collector command shared by every official-site source."""
from __future__ import annotations

import argparse
import json
from types import ModuleType
from typing import Sequence


def run_collection_cli(
    *,
    brand_name: str,
    config: ModuleType,
    database: ModuleType,
    run_service: ModuleType,
    argv: Sequence[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=f"Run one {brand_name} price/offer collection pass."
    )
    parser.add_argument(
        "--channel",
        default="BOTH",
        choices=["PICKUP", "DELIVERY", "BOTH"],
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Skip screenshot capture for new product and offer events",
    )
    args = parser.parse_args(argv)

    config.ensure_directories()
    database.init_db()

    print(
        f"[RUN] Starting {brand_name} collection "
        f"(channel={args.channel}, branch={config.BRANCH_NAME} "
        f"storeId={config.BRANCH_STORE_ID})"
    )
    try:
        summary = run_service.run_collection(
            channel=args.channel,
            trigger="MANUAL",
            enable_screenshots=not args.no_screenshots,
        )
    except run_service.RunAlreadyInProgressError as error:
        print(f"[RUN] Refused to start: {error}")
        return 2

    print(f"[RUN] Finished. Overall status: {summary['overall_status']}")
    for channel in summary["channels"]:
        print(
            f"  - {channel['channel']}: {channel['status']} "
            f"(products={channel.get('product_count', 0)}, "
            f"offers={channel.get('offer_count', 0)})"
        )
        change = channel.get("change_summary")
        if not isinstance(change, dict) or "products" not in change:
            continue
        products = change["products"]
        offers = change["offers"]
        print(
            "      "
            f"new_products={products['new_product']} "
            f"price_up={products['price_increase']} "
            f"price_down={products['price_decrease']} "
            f"not_observed={products['not_observed']} "
            f"removed={products['removed']} returned={products['returned']}"
        )
        print(
            "      "
            f"new_offers={offers['new_offer']} changed={offers['changed']} "
            f"not_observed={offers['not_observed']} ended={offers['ended']} "
            f"returned={offers['returned']}"
        )

    print(f"[RUN] Screenshots captured: {summary['screenshots_captured']}")
    print(f"[RUN] Full summary JSON: {json.dumps(summary, default=str)}")
    return 0 if summary["overall_status"] != "FAILED" else 1
