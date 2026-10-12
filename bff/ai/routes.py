"""HTTP routes for the AI section. Kept apart from the core BFF routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from bff.ai import mapping, store
from bff.contract import Channel, ContractModel
from bff.registry import get_adapter

router = APIRouter(prefix="/ai")


class SuggestRequest(ContractModel):
    kudu_product_id: str = Field(min_length=1)
    channel: Channel


@router.get("/status")
def ai_status() -> dict[str, Any]:
    return {
        "configured": mapping.is_configured(),
        "model": mapping.model_name(),
        **store.summary(),
    }


@router.post("/mapping/suggest")
def suggest_mapping(payload: SuggestRequest) -> dict[str, Any]:
    kudu = get_adapter("kudu")
    product = kudu.get_product(payload.kudu_product_id) if kudu else None
    if product is None or product.channel != payload.channel:
        raise HTTPException(
            status_code=404,
            detail={"error": "kudu_product_not_found", "message": "That KUDU item is not in this channel."},
        )
    if not mapping.is_configured():
        raise HTTPException(
            status_code=409,
            detail={"error": "ai_not_configured", "message": "ANTHROPIC_API_KEY is not set on the server."},
        )
    try:
        return mapping.suggest(product, payload.channel)
    except mapping.AiError as error:
        raise HTTPException(status_code=502, detail={"error": "ai_failed", "message": str(error)}) from None
