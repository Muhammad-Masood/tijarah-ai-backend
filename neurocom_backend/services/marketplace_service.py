import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import Session, select

from neurocom_backend.database.models.marketplace import (
    ConnectMarketplaceRequest,
    Marketplace,
    MarketplaceConnection,
    MarketplaceConnectionRead,
    MarketplaceCreate,
    MarketplaceRead,
    MarketplaceUpdate,
)
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.services.daraz_service import get_access_token
from neurocom_backend.services.shopify_service import (
    encode_shopify_credentials,
    get_access_token as get_shopify_access_token,
    normalize_shop,
)
from neurocom_backend.utils.security import encrypt_value

DARAZ_SLUG = "daraz"
SHOPIFY_SLUG = "shopify"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def is_daraz_marketplace(marketplace: Marketplace) -> bool:
    slug = marketplace.slug.strip().lower()
    name = marketplace.name.strip().lower()
    return slug == DARAZ_SLUG or slug.startswith(f"{DARAZ_SLUG}-") or name == DARAZ_SLUG


def is_shopify_marketplace(marketplace: Marketplace) -> bool:
    slug = marketplace.slug.strip().lower()
    name = marketplace.name.strip().lower()
    return slug == SHOPIFY_SLUG or slug.startswith(f"{SHOPIFY_SLUG}-") or name == SHOPIFY_SLUG


def _to_marketplace_read(marketplace: Marketplace, is_connected: bool = False) -> MarketplaceRead:
    return MarketplaceRead(
        id=marketplace.id,
        name=marketplace.name,
        slug=marketplace.slug,
        url=marketplace.url,
        logo_url=marketplace.logo_url,
        is_connected=is_connected,
    )


def _to_connection_read(connection: MarketplaceConnection) -> MarketplaceConnectionRead:
    marketplace_read = None
    if connection.marketplace is not None:
        marketplace_read = _to_marketplace_read(connection.marketplace, is_connected=True)
    return MarketplaceConnectionRead(
        id=connection.id,
        marketplace_id=connection.marketplace_id,
        merchant_id=connection.merchant_id,
        connected_at=connection.connected_at,
        encrypted_access_token=connection.encrypted_access_token,
        marketplace=marketplace_read,
    )


def _get_marketplace_or_404(db: Session, marketplace_id: UUID) -> Marketplace:
    marketplace = db.get(Marketplace, marketplace_id)
    if marketplace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace not found")
    return marketplace


def _ensure_unique_name_and_slug(
    db: Session,
    name: str,
    slug: str,
    exclude_id: UUID | None = None,
) -> None:
    name_query = select(Marketplace).where(Marketplace.name == name)
    slug_query = select(Marketplace).where(Marketplace.slug == slug)
    if exclude_id is not None:
        name_query = name_query.where(Marketplace.id != exclude_id)
        slug_query = slug_query.where(Marketplace.id != exclude_id)

    if db.exec(name_query).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Marketplace name already exists")
    if db.exec(slug_query).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Marketplace slug already exists")


def create_marketplace(payload: MarketplaceCreate, db: Session) -> MarketplaceRead:
    slug = slugify(payload.slug or payload.name)
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not generate a marketplace slug")
    _ensure_unique_name_and_slug(db, payload.name, slug)

    marketplace = Marketplace(
        name=payload.name,
        slug=slug,
        url=payload.url,
        logo_url=payload.logo_url,
    )
    db.add(marketplace)
    db.commit()
    db.refresh(marketplace)
    return _to_marketplace_read(marketplace)


def list_marketplaces(db: Session, merchant: Merchant) -> list[MarketplaceRead]:
    marketplaces = db.exec(select(Marketplace)).all()
    connected_ids = set(
        db.exec(
            select(MarketplaceConnection.marketplace_id).where(
                MarketplaceConnection.merchant_id == merchant.id
            )
        ).all()
    )
    return [_to_marketplace_read(marketplace, marketplace.id in connected_ids) for marketplace in marketplaces]


def get_marketplace(marketplace_id: UUID, db: Session, merchant: Merchant) -> MarketplaceRead:
    marketplace = _get_marketplace_or_404(db, marketplace_id)
    connection = db.exec(
        select(MarketplaceConnection).where(
            MarketplaceConnection.merchant_id == merchant.id,
            MarketplaceConnection.marketplace_id == marketplace_id,
        )
    ).first()
    return _to_marketplace_read(marketplace, connection is not None)


def update_marketplace(marketplace_id: UUID, payload: MarketplaceUpdate, db: Session) -> MarketplaceRead:
    marketplace = _get_marketplace_or_404(db, marketplace_id)
    updates = payload.model_dump(exclude_unset=True)
    name = updates.get("name", marketplace.name)
    slug_source = updates.get("slug") or (name if "name" in updates else marketplace.slug)
    slug = slugify(slug_source)
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not generate a marketplace slug")

    _ensure_unique_name_and_slug(db, name, slug, exclude_id=marketplace_id)

    marketplace.name = name
    marketplace.slug = slug
    if "url" in updates:
        marketplace.url = updates["url"]
    if "logo_url" in updates:
        marketplace.logo_url = updates["logo_url"]

    db.add(marketplace)
    db.commit()
    db.refresh(marketplace)
    return _to_marketplace_read(marketplace)


def delete_marketplace(marketplace_id: UUID, db: Session) -> MarketplaceRead:
    marketplace = _get_marketplace_or_404(db, marketplace_id)
    connections = db.exec(
        select(MarketplaceConnection).where(MarketplaceConnection.marketplace_id == marketplace_id)
    ).all()
    for connection in connections:
        db.delete(connection)

    response = _to_marketplace_read(marketplace)
    db.delete(marketplace)
    db.commit()
    return response


def _resolve_shopify_credentials(payload: ConnectMarketplaceRequest) -> str:
    if not payload.shop or not payload.shop.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify connect requires a shop domain",
        )
    shop = normalize_shop(payload.shop)

    if payload.access_token:
        return encode_shopify_credentials(shop, payload.access_token.strip())
    if not payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify connect requires an OAuth code or access token",
        )
    try:
        token_response = get_shopify_access_token(payload.code, shop)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange Shopify authorization code",
        )
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify did not return an access token",
        )
    return encode_shopify_credentials(shop, access_token)


def _resolve_daraz_access_token(payload: ConnectMarketplaceRequest) -> str:
    if payload.access_token:
        return payload.access_token.strip()
    if not payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Daraz connect requires an OAuth code or access token",
        )
    try:
        access_token = get_access_token(payload.code)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange Daraz authorization code",
        )
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Daraz did not return an access token",
        )
    return access_token


def connect_marketplace(
    marketplace_id: UUID,
    payload: ConnectMarketplaceRequest,
    db: Session,
    merchant: Merchant,
) -> MarketplaceConnectionRead:
    marketplace = _get_marketplace_or_404(db, marketplace_id)
    encrypted_token = None

    if is_daraz_marketplace(marketplace):
        access_token = _resolve_daraz_access_token(payload)
        encrypted_token = encrypt_value(access_token)
    elif is_shopify_marketplace(marketplace):
        credentials_json = _resolve_shopify_credentials(payload)
        encrypted_token = encrypt_value(credentials_json)
    elif payload.access_token:
        encrypted_token = encrypt_value(payload.access_token.strip())

    connection = db.exec(
        select(MarketplaceConnection).where(
            MarketplaceConnection.merchant_id == merchant.id,
            MarketplaceConnection.marketplace_id == marketplace_id,
        )
    ).first()

    if connection is None:
        connection = MarketplaceConnection(
            merchant_id=merchant.id,
            marketplace_id=marketplace_id,
            encrypted_access_token=encrypted_token,
        )
    else:
        if encrypted_token is not None:
            connection.encrypted_access_token = encrypted_token

    db.add(connection)
    db.commit()
    db.refresh(connection)
    connection.marketplace = marketplace
    return _to_connection_read(connection)


def list_merchant_connections(db: Session, merchant: Merchant) -> list[MarketplaceConnectionRead]:
    connections = db.exec(
        select(MarketplaceConnection).where(MarketplaceConnection.merchant_id == merchant.id)
    ).all()
    for connection in connections:
        _ = connection.marketplace
    return [_to_connection_read(connection) for connection in connections]


def disconnect_marketplace(connection_id: UUID, db: Session, merchant: Merchant) -> MarketplaceConnectionRead:
    connection = db.get(MarketplaceConnection, connection_id)
    if connection is None or connection.merchant_id != merchant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Marketplace connection not found")

    _ = connection.marketplace
    response = _to_connection_read(connection)
    db.delete(connection)
    db.commit()
    return response
