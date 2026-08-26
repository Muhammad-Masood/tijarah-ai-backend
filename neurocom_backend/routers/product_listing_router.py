"""
AI product-listing generation: image + Daraz category attributes → draft
aligned with create_new_product. JWT-only (no Daraz access token) — the
client already fetched attributes via /daraz/get_category_attributes.
"""

from fastapi import APIRouter, HTTPException

from neurocom_backend.models.product_listing_model import (
    GenerateListingRequest,
    GenerateListingResponse,
)
from neurocom_backend.services.product_listing_service import generate_product_listing

router = APIRouter(prefix="/product-listing", tags=["Product Listing"])


@router.post("/generate", response_model=GenerateListingResponse)
async def generate_listing(request: GenerateListingRequest):
    try:
        return generate_product_listing(request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Listing generation failed: {exc}") from exc
