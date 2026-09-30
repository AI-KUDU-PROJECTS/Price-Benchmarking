"""HTTP routes. Compose adapters; contain no restaurant SQL."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from bff.contract import (
    BrandOverview,
    BrandStatusRow,
    Channel,
    EventType,
    ListMeta,
    MarketCounts,
    MarketOverview,
    PromotionStatus,
    PriceMappingList,
    PriceMappingWrite,
    dump,
    now_riyadh_iso,
    select_highlights,
)
from bff.playground import (
    create_mapping,
    delete_mapping,
    get_mapping,
    list_mappings,
    update_mapping,
)
from bff.registry import all_brands, connected_adapters, get_adapter
from bff.pull_all import hungerstation_pull_manager, pull_manager

router = APIRouter()


@router.post("/market/pull", status_code=202)
def start_market_pull() -> dict[str, Any]:
    run, started = pull_manager.start()
    return {"run": run, "started": started}


@router.get("/market/pull")
def market_pull_status() -> dict[str, Any]:
    return {"run": pull_manager.latest()}


@router.post("/market/hungerstation/pull", status_code=202)
def start_hungerstation_pull() -> dict[str, Any]:
    run, started = hungerstation_pull_manager.start()
    return {"run": run, "started": started}


@router.get("/market/hungerstation/pull")
def hungerstation_pull_status() -> dict[str, Any]:
    return {"run": hungerstation_pull_manager.latest()}

def _meta(items: list[Any], freshness: str, source_run_ids: list[str],
          page: int = 1, page_size: int | None = None) -> dict[str, Any]:
    total = len(items)
    size = page_size if page_size is not None else total or 1
    start = (page - 1) * size
    slice_ = items[start:start + size]
    return {
        "items": [dump(item) for item in slice_],
        "meta": dump(
            ListMeta(
                page=page,
                page_size=size,
                total=total,
                freshness=freshness,  # type: ignore[arg-type]
                source_run_ids=source_run_ids,
                generated_at=now_riyadh_iso(),
            )
        ),
    }


def _market_adapters(brand_id: str | None = None) -> dict[str, Any]:
    if brand_id:
        return {brand_id: _require_adapter(brand_id)}
    return connected_adapters()


def _market_freshness(adapters: dict[str, Any]) -> str:
    freshness_values = [adapter.get_brand().data_freshness for adapter in adapters.values()]
    if not freshness_values or all(value == "unavailable" for value in freshness_values):
        return "unavailable"
    return "fresh" if all(value == "fresh" for value in freshness_values) else "stale"


def _require_adapter(brand_id: str):
    adapter = get_adapter(brand_id)
    if adapter is None:
        known = {item.id for item in all_brands()}
        if brand_id in known:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "brand_not_connected",
                    "brandId": brand_id,
                    "message": "This brand is not connected.",
                },
            )
        raise HTTPException(status_code=404, detail={"error": "unknown_brand", "brandId": brand_id})
    return adapter


@router.get("/market/overview")
def market_overview() -> dict[str, Any]:
    adapters = connected_adapters()
    brand_rows: list[BrandStatusRow] = []
    highlights_source = []
    last_updated = None
    freshness_values = []
    counts = MarketCounts()

    for brand in all_brands():
        adapter = adapters.get(brand.id)
        if adapter is None:
            brand_rows.append(BrandStatusRow(brand=brand))
            continue
        overview: BrandOverview = adapter.get_overview()
        changes = adapter.list_changes()
        window = overview.recent_changes
        counts.price_decreases += sum(1 for e in window if e.type == "price_decreased")
        counts.price_increases += sum(1 for e in window if e.type == "price_increased")
        counts.new_products += sum(1 for e in window if e.type == "product_added")
        counts.new_offers += sum(1 for e in window if e.type == "offer_started")
        counts.ended_offers += sum(1 for e in window if e.type == "offer_ended")
        highlights_source.extend(window)
        freshness_values.append(brand.data_freshness)
        if brand.last_successful_run_at and (
            last_updated is None or brand.last_successful_run_at > last_updated
        ):
            last_updated = brand.last_successful_run_at
        brand_rows.append(
            BrandStatusRow(
                brand=overview.brand,
                product_count=overview.product_count,
                promotion_count=overview.promotion_count,
                change_count=len(changes),
            )
        )

    if not adapters:
        market_freshness = "unavailable"
    elif any(v == "unavailable" for v in freshness_values) and not any(
        v == "fresh" or v == "stale" for v in freshness_values
    ):
        market_freshness = "unavailable"
    elif all(v == "fresh" for v in freshness_values):
        market_freshness = "fresh"
    else:
        market_freshness = "stale"

    payload = MarketOverview(
        last_updated_at=last_updated,
        freshness=market_freshness,  # type: ignore[arg-type]
        connected_brand_ids=list(adapters),
        counts=counts,
        highlights=select_highlights(highlights_source),
        brands=brand_rows,
    )
    return dump(payload)


@router.get("/market/changes")
def market_changes(
    brand: str | None = None,
    channel: Channel | None = None,
    type: EventType | str | None = Query(default=None, alias="type"),
    category: str | None = None,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    adapters = _market_adapters(brand)
    items = []
    for adapter in adapters.values():
        items.extend(
            adapter.list_changes(
                channel=channel,
                event_type=type,
                category=category,
                date_from=date_from,
                date_to=date_to,
            )
        )
    items.sort(key=lambda event: event.detected_at, reverse=True)
    source_run_ids = sorted({event.source_run_id for event in items if event.source_run_id})
    return _meta(
        items,
        _market_freshness(adapters),
        source_run_ids,
        page=page,
        page_size=page_size,
    )


@router.get("/market/promotions")
def market_promotions(
    brand: str | None = None,
    channel: Channel | None = None,
    status: PromotionStatus | str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    adapters = _market_adapters(brand)
    items = []
    for adapter in adapters.values():
        items.extend(
            adapter.list_promotions(
                channel=channel,
                status=status,
                category=category,
                query=q,
            )
        )
    items.sort(key=lambda promotion: (promotion.last_seen_at or "", promotion.title or ""), reverse=True)
    return _meta(items, _market_freshness(adapters), [], page=page, page_size=page_size)


@router.get("/brands")
def list_brands() -> dict[str, Any]:
    brands = all_brands()
    freshness = _market_freshness(connected_adapters())
    return _meta(brands, freshness, [])


@router.get("/brands/{brand_id}/overview")
def brand_overview(brand_id: str) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    return dump(adapter.get_overview())


@router.get("/brands/{brand_id}/products")
def brand_products(
    brand_id: str,
    channel: Channel | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    items = adapter.list_products(channel=channel, category=category, query=q)
    brand = adapter.get_brand()
    run_ids = sorted({p.source_run_id for p in items if p.source_run_id})
    return _meta(items, brand.data_freshness, run_ids, page=page, page_size=page_size)


@router.get("/brands/{brand_id}/products/{product_id}/history")
def brand_product_history(brand_id: str, product_id: str) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    history = adapter.get_product_history(product_id)
    if history is None:
        raise HTTPException(status_code=404, detail={"error": "product_not_found", "id": product_id})
    return dump(history)


@router.get("/brands/{brand_id}/products/{product_id}")
def brand_product(brand_id: str, product_id: str) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    product = adapter.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail={"error": "product_not_found", "id": product_id})
    return dump(product)


@router.get("/brands/{brand_id}/promotions/{promotion_id}")
def brand_promotion(brand_id: str, promotion_id: str) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    promotion = adapter.get_promotion(promotion_id)
    if promotion is None:
        raise HTTPException(status_code=404, detail={"error": "promotion_not_found", "id": promotion_id})
    return dump(promotion)


@router.get("/brands/{brand_id}/promotions")
def brand_promotions(
    brand_id: str,
    channel: Channel | None = None,
    status: PromotionStatus | str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    items = adapter.list_promotions(channel=channel, status=status, category=category, query=q)
    brand = adapter.get_brand()
    return _meta(items, brand.data_freshness, [], page=page, page_size=page_size)


@router.get("/brands/{brand_id}/changes")
def brand_changes(
    brand_id: str,
    channel: Channel | None = None,
    type: EventType | str | None = Query(default=None, alias="type"),
    category: str | None = None,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    adapter = _require_adapter(brand_id)
    items = adapter.list_changes(
        channel=channel,
        event_type=type,
        category=category,
        date_from=date_from,
        date_to=date_to,
    )
    brand = adapter.get_brand()
    run_ids = sorted({e.source_run_id for e in items if e.source_run_id})
    return _meta(items, brand.data_freshness, run_ids, page=page, page_size=page_size)


@router.get("/changes/{change_id}")
def get_change(change_id: str) -> dict[str, Any]:
    for adapter in connected_adapters().values():
        event = adapter.get_change(change_id)
        if event is not None:
            return dump(event)
    raise HTTPException(status_code=404, detail={"error": "change_not_found", "id": change_id})


@router.get("/playground/mappings")
def playground_mappings() -> dict[str, Any]:
    return dump(PriceMappingList(items=list_mappings()))


@router.get("/playground/mappings/{mapping_id}")
def playground_mapping(mapping_id: str) -> dict[str, Any]:
    mapping = get_mapping(mapping_id)
    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "mapping_not_found", "id": mapping_id},
        )
    return dump(mapping)


@router.post("/playground/mappings", status_code=201)
def create_playground_mapping(payload: PriceMappingWrite) -> dict[str, Any]:
    return dump(create_mapping(payload))


@router.put("/playground/mappings/{mapping_id}")
def update_playground_mapping(
    mapping_id: str,
    payload: PriceMappingWrite,
) -> dict[str, Any]:
    mapping = update_mapping(mapping_id, payload)
    if mapping is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "mapping_not_found", "id": mapping_id},
        )
    return dump(mapping)


@router.delete("/playground/mappings/{mapping_id}", status_code=204)
def delete_playground_mapping(mapping_id: str) -> Response:
    if not delete_mapping(mapping_id):
        raise HTTPException(
            status_code=404,
            detail={"error": "mapping_not_found", "id": mapping_id},
        )
    return Response(status_code=204)
