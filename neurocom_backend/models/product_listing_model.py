"""DTOs for AI product-listing generation from a product image + Daraz
category attributes. The draft shape mirrors the live create_new_product
JSON body (Title / PrimaryCategory / Images / Attributes / Skus)."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

from neurocom_backend.models.daraz_model import CategoryAttribute


class GenerateListingRequest(BaseModel):
    primary_category_id: int
    image_urls: List[HttpUrl] = Field(..., min_length=1)
    attributes: List[CategoryAttribute] = Field(..., min_length=1)
    title_hint: Optional[str] = None
    brand_hint: Optional[str] = None


class FilledAttribute(BaseModel):
    name: str
    value: Optional[str] = None
    source: Literal["vision", "user_required", "skipped"]
    confidence: Optional[float] = None


class ListingSkuDraft(BaseModel):
    SellerSku: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    package_length: Optional[float] = None
    package_height: Optional[float] = None
    package_weight: Optional[float] = None
    package_width: Optional[float] = None
    package_content: Optional[str] = None
    color_family: Optional[str] = None
    size: Optional[str] = None
    Images: List[str] = []


class ListingDraft(BaseModel):
    """Drop-in shape for the create-product form / Body of create_new_product."""

    Title: Optional[str] = None
    PrimaryCategory: int
    Images: List[str]
    Attributes: Dict[str, Optional[str]]
    Skus: List[ListingSkuDraft]


class GenerateListingResponse(BaseModel):
    draft: ListingDraft
    filled: List[FilledAttribute]
    user_required: List[str]
    vision_skipped: List[str]
