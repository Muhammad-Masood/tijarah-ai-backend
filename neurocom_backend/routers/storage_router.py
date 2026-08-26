from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.marketplace import Marketplace, MarketplaceConnection
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.dependencies import get_current_user
from neurocom_backend.services.storage_service import ALLOWED_IMAGE_TYPES, MAX_IMAGE_SIZE, delete_product_images, upload_product_image

router = APIRouter(prefix="/storage", tags=["Storage"])
MarketplaceSlug = Literal["daraz", "shopify"]


class ProductImageUploadResponse(BaseModel):
    path: str
    public_url: str
    content_type: str
    size: int


class ProductImageCleanupRequest(BaseModel):
    paths: list[str]


class ProductImageCleanupResponse(BaseModel):
    deleted: list[str]


def _require_connection(db: Session, merchant: Merchant, slug: str) -> None:
    connection = db.exec(select(MarketplaceConnection).join(Marketplace).where(MarketplaceConnection.merchant_id == merchant.id, Marketplace.slug == slug, MarketplaceConnection.encrypted_access_token.is_not(None))).first()
    if connection is None or not connection.encrypted_access_token:
        raise HTTPException(status_code=409, detail=f"No active {slug.title()} connection")


def _matches_image_signature(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    return content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP"


@router.post("/product-images", response_model=ProductImageUploadResponse)
async def upload_marketplace_product_image(file: Annotated[UploadFile, File()], marketplace: Annotated[MarketplaceSlug, Form()], db: Annotated[Session, Depends(get_session)], current_user: Annotated[Merchant, Depends(get_current_user)]):
    _require_connection(db, current_user, marketplace)
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type. Use JPEG, PNG, or WebP")
    content = await file.read(MAX_IMAGE_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Image file is empty")
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Image file exceeds the 5 MB limit")
    if not _matches_image_signature(content_type, content):
        raise HTTPException(status_code=400, detail="File content is not a valid image")
    return upload_product_image(current_user.id, marketplace, file.filename, content_type, content)


@router.post("/product-images/cleanup", response_model=ProductImageCleanupResponse)
async def cleanup_marketplace_product_images(payload: ProductImageCleanupRequest, current_user: Annotated[Merchant, Depends(get_current_user)]):
    return {"deleted": delete_product_images(current_user.id, payload.paths)}
