from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlmodel import Session

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.marketplace import (
    ConnectMarketplaceRequest,
    MarketplaceConnectionRead,
    MarketplaceCreate,
    MarketplaceRead,
    PublishConnectedProductRequest,
    PublishConnectedProductResponse,
    MarketplaceUpdate,
)
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.dependencies import get_current_user, require_admin
from neurocom_backend.services.marketplace_service import (
    connect_marketplace,
    create_marketplace,
    delete_marketplace,
    disconnect_marketplace,
    get_marketplace,
    list_marketplaces,
    list_merchant_connections,
    update_marketplace,
)
from neurocom_backend.services.marketplace_publishing_service import publish_to_connected_stores

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])




@router.post("/publish-to-connected-stores", response_model=PublishConnectedProductResponse)
async def publish_to_my_connected_stores(
    payload: PublishConnectedProductRequest,
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return publish_to_connected_stores(payload=payload, db=db, merchant=current_user)
@router.post("/", response_model=MarketplaceRead)
async def create_supported_marketplace(
    payload: MarketplaceCreate,
    db: Annotated[Session, Depends(get_session)],
    _: Annotated[Merchant, Depends(require_admin)],
):
    return create_marketplace(payload=payload, db=db)


@router.get("/", response_model=list[MarketplaceRead])
async def get_supported_marketplaces(
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return list_marketplaces(db=db, merchant=current_user)


@router.get("/connections", response_model=list[MarketplaceConnectionRead])
async def get_my_marketplace_connections(
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return list_merchant_connections(db=db, merchant=current_user)


@router.delete("/connections/{connection_id}", response_model=MarketplaceConnectionRead)
async def delete_my_marketplace_connection(
    connection_id: UUID,
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return disconnect_marketplace(connection_id=connection_id, db=db, merchant=current_user)


@router.get("/{marketplace_id}", response_model=MarketplaceRead)
async def get_supported_marketplace(
    marketplace_id: UUID,
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return get_marketplace(marketplace_id=marketplace_id, db=db, merchant=current_user)


@router.put("/{marketplace_id}", response_model=MarketplaceRead)
async def update_supported_marketplace(
    marketplace_id: UUID,
    payload: MarketplaceUpdate,
    db: Annotated[Session, Depends(get_session)],
    _: Annotated[Merchant, Depends(require_admin)],
):
    return update_marketplace(marketplace_id=marketplace_id, payload=payload, db=db)


@router.delete("/{marketplace_id}", response_model=MarketplaceRead)
async def delete_supported_marketplace(
    marketplace_id: UUID,
    db: Annotated[Session, Depends(get_session)],
    _: Annotated[Merchant, Depends(require_admin)],
):
    return delete_marketplace(marketplace_id=marketplace_id, db=db)


@router.post("/{marketplace_id}/connect", response_model=MarketplaceConnectionRead)
async def connect_supported_marketplace(
    marketplace_id: UUID,
    payload: ConnectMarketplaceRequest,
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
):
    return connect_marketplace(
        marketplace_id=marketplace_id,
        payload=payload,
        db=db,
        merchant=current_user,
    )
