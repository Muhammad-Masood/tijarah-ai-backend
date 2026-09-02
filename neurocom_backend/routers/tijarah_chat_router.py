"""
WebSocket router for the Tijarah multi-marketplace chat agent.

Same auth caveat as product_chat_router.py: this router is registered in
main.py WITHOUT dependencies=require_auth because OAuth2PasswordBearer
does not work with WebSocket connections. Auth is handled per-route via
get_current_user_ws (a websocket-safe JWT check).

Marketplace tokens are optional WebSocket headers:
  - x-daraz-access-token: encrypted Daraz token (optional)
  - x-shopify-access-token: encrypted Shopify credentials (optional)

If neither is provided, the router auto-resolves all connected marketplaces
from the merchant's MarketplaceConnection records in the database.
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, WebSocketException
from sqlmodel import Session, select

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.marketplace import Marketplace, MarketplaceConnection
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.dependencies import get_current_user_ws
from neurocom_backend.services.marketplace_service import (
    DARAZ_SLUG,
    SHOPIFY_SLUG,
    is_daraz_marketplace,
    is_shopify_marketplace,
)
from neurocom_backend.services.shopify_service import decode_shopify_credentials
from neurocom_backend.services.tijarah_chat_service import TijarahContext, build_tijarah_agent, stream_tijarah_response
from neurocom_backend.utils.security import decrypt_value

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tijarah", tags=["Tijarah Chat"])


def _resolve_daraz_token_from_connection(
    db: Session, merchant: Merchant, encrypted_token: str
) -> str:
    """Verify the encrypted Daraz token belongs to this merchant and decrypt it."""
    connection = db.exec(
        select(MarketplaceConnection)
        .join(Marketplace)
        .where(
            MarketplaceConnection.merchant_id == merchant.id,
            Marketplace.slug == DARAZ_SLUG,
            MarketplaceConnection.encrypted_access_token == encrypted_token,
        )
    ).first()
    if connection is None:
        raise WebSocketException(
            code=4003,
            reason="Daraz connection is not active for the authenticated merchant",
        )
    try:
        return decrypt_value(encrypted_token)
    except Exception:
        raise WebSocketException(
            code=4003,
            reason="Invalid encrypted Daraz access token",
        )


def _resolve_shopify_creds_from_connection(
    db: Session, merchant: Merchant, encrypted_token: str
) -> tuple[str, str]:
    """Verify the encrypted Shopify token belongs to this merchant and decrypt it."""
    connection = db.exec(
        select(MarketplaceConnection)
        .join(Marketplace)
        .where(
            MarketplaceConnection.merchant_id == merchant.id,
            Marketplace.slug == SHOPIFY_SLUG,
            MarketplaceConnection.encrypted_access_token == encrypted_token,
        )
    ).first()
    if connection is None:
        raise WebSocketException(
            code=4003,
            reason="Shopify connection is not active for the authenticated merchant",
        )
    try:
        decrypted = decrypt_value(encrypted_token)
        return decode_shopify_credentials(decrypted)
    except Exception:
        raise WebSocketException(
            code=4003,
            reason="Invalid encrypted Shopify access token",
        )


def _auto_resolve_connections(
    db: Session, merchant: Merchant
) -> TijarahContext:
    """Resolve all connected marketplaces from the merchant's DB records."""
    connections = db.exec(
        select(MarketplaceConnection)
        .join(Marketplace)
        .where(MarketplaceConnection.merchant_id == merchant.id)
    ).all()

    ctx = TijarahContext()

    for connection in connections:
        marketplace = connection.marketplace
        if marketplace is None:
            continue

        if is_daraz_marketplace(marketplace) and connection.encrypted_access_token:
            try:
                ctx.daraz_access_token = decrypt_value(connection.encrypted_access_token)
            except Exception as e:
                logger.warning("Failed to decrypt Daraz token for merchant %s: %s", merchant.id, e)

        elif is_shopify_marketplace(marketplace) and connection.encrypted_access_token:
            try:
                decrypted = decrypt_value(connection.encrypted_access_token)
                shop, access_token = decode_shopify_credentials(decrypted)
                ctx.shopify_shop = shop
                ctx.shopify_access_token = access_token
            except Exception as e:
                logger.warning("Failed to decrypt Shopify token for merchant %s: %s", merchant.id, e)

    return ctx


@router.websocket("/ask_tijarah")
async def ask_tijarah(
    websocket: WebSocket,
    merchant: Merchant = Depends(get_current_user_ws),
    db: Session = Depends(get_session),
):
    """
    Multi-marketplace conversational agent for Tijarah merchants.

    The agent can answer questions about products, orders, reviews, financials,
    and operations across Daraz and Shopify.

    Optional headers to scope the session:
      - x-daraz-access-token: encrypted Daraz token (scopes to Daraz only)
      - x-shopify-access-token: encrypted Shopify credentials (scopes to Shopify only)

    If neither header is provided, the agent auto-resolves all connected
    marketplaces from the merchant's database records.

    Once connected, send {"message": "..."} per turn. The agent responds with
    streaming events: token, tool_start, tool_end, visualization, done, error.
    """
    await websocket.accept()

    # Resolve marketplace credentials
    daraz_header = websocket.headers.get("x-daraz-access-token", "").strip()
    shopify_header = websocket.headers.get("x-shopify-access-token", "").strip()

    if daraz_header or shopify_header:
        # Explicit tokens provided in headers
        ctx = TijarahContext()

        if daraz_header:
            ctx.daraz_access_token = _resolve_daraz_token_from_connection(db, merchant, daraz_header)

        if shopify_header:
            ctx.shopify_shop, ctx.shopify_access_token = _resolve_shopify_creds_from_connection(
                db, merchant, shopify_header
            )
    else:
        # Auto-resolve from merchant's connected marketplaces
        ctx = _auto_resolve_connections(db, merchant)

    if not ctx.available_marketplaces:
        await websocket.send_json({
            "event": "error",
            "data": {
                "detail": "No marketplace connections found. Please connect at least one marketplace (Daraz or Shopify) before using Tijarah Chat."
            },
        })
        await websocket.close(code=4003, reason="No marketplace connections")
        return

    # Build the agent for this session
    agent = build_tijarah_agent(ctx)
    thread_id = str(uuid.uuid4())

    # Send a welcome message with context
    marketplace_names = ", ".join(m.capitalize() for m in ctx.available_marketplaces)
    await websocket.send_json({
        "event": "connected",
        "data": {
            "message": f"Tijarah Chat connected. Available marketplaces: {marketplace_names}",
            "marketplaces": ctx.available_marketplaces,
        },
    })

    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception:
                await websocket.send_json({
                    "event": "error",
                    "data": {"detail": "Message must be valid JSON with a 'message' field."},
                })
                continue

            message = (payload or {}).get("message", "").strip()
            if not message:
                await websocket.send_json({
                    "event": "error",
                    "data": {"detail": "Missing 'message' field."},
                })
                continue

            async for event, data in stream_tijarah_response(agent, thread_id, message):
                print("event: ", event, "data: ", data)
                await websocket.send_json({"event": event, "data": data})

    except WebSocketDisconnect:
        pass
