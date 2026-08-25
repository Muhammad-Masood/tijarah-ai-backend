"""
Separate from reviews_router on purpose: main.py applies merchant-JWT auth
at include_router(..., dependencies=require_auth) time, which wraps every
route on a router uniformly — including websocket ones. require_auth
resolves to Depends(get_current_user), which depends on
OAuth2PasswordBearer, and that class's __call__ hard-requires an HTTP
Request; resolved against a websocket connection it raises a bare
TypeError before this endpoint's own code ever runs. There's no per-route
way to opt out of a router-level dependency, so this router is registered
in main.py WITHOUT dependencies=require_auth, and auth is done per-route
here instead via dependencies.get_current_user_ws (a websocket-safe
reimplementation of the same JWT check).
"""

import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from typing import Optional

from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.dependencies import get_current_user_ws
from neurocom_backend.routers.daraz_router import get_daraz_access_token
from neurocom_backend.services.product_chat_service import build_product_chat_agent, stream_product_chat_response

router = APIRouter(prefix="/reviews", tags=["Reviews Analysis"])


@router.websocket("/product_chat")
async def product_chat(
    websocket: WebSocket,
    product_id: int,
    product_sku_id: Optional[str] = None,
    merchant: Merchant = Depends(get_current_user_ws),
    access_token: str = Depends(get_daraz_access_token),
):
    """
    Chat about ONE product's reviews/ratings, catalog details, and orders
    (especially returns). product_id/product_sku_id scope the whole session
    — the client sends only {"message": "..."} per turn.

    One agent (and its LangGraph MemorySaver thread) per connection, so
    multi-turn context works within a session; it's gone once the socket
    closes, and isn't shared across worker processes — see
    product_chat_service's module docstring for the production caveat.
    """
    await websocket.accept()
    agent = build_product_chat_agent(access_token, product_id, product_sku_id)
    thread_id = str(uuid.uuid4())

    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception:
                await websocket.send_json({"event": "error", "data": {"detail": "Message must be valid JSON with a 'message' field."}})
                continue

            message = (payload or {}).get("message", "").strip()
            if not message:
                await websocket.send_json({"event": "error", "data": {"detail": "Missing 'message' field."}})
                continue

            async for event, data in stream_product_chat_response(agent, thread_id, message):
                print("event: ", event)
                print("data: ", data)
                await websocket.send_json({"event": event, "data": data})
    except WebSocketDisconnect:
        pass
