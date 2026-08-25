import uuid
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from typing import Optional
from dotenv import load_dotenv
from neurocom_backend.models.review_model import ReviewAnalysisResponse, AnalysisRequest
from neurocom_backend.services.reviews_service import analyze_reviews_with_llm, analyze_reviews_with_llm_stream, reviews_from_scraped
from neurocom_backend.services.daraz_service import scrape_product_reviews
from neurocom_backend.services.product_chat_service import build_product_chat_agent, stream_product_chat_response
from neurocom_backend.routers.daraz_router import get_daraz_access_token
from neurocom_backend.utils.sse import sse_stream

_:bool = load_dotenv()

router  = APIRouter(prefix="/reviews",tags=["Reviews Analysis"])

@router.get('/')
async def root():
    return {"message": "Reviews Analysis Router"}

@router.post("/analyze-reviews", response_model=ReviewAnalysisResponse)
async def analyze_product_reviews(request: AnalysisRequest):
    try:
        scraped = scrape_product_reviews(request.product_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not scraped.reviews:
        raise HTTPException(status_code=400, detail="No reviews found for this product")

    reviews = reviews_from_scraped(scraped)
    if not reviews:
        raise HTTPException(status_code=400, detail="No usable review content found for this product")

    if request.stream:
        return StreamingResponse(
            sse_stream(analyze_reviews_with_llm_stream(request.product_name, scraped.item_id, reviews)),
            media_type="text/event-stream",
        )

    # Run Analysis
    data = analyze_reviews_with_llm(request.product_name, scraped.item_id, reviews)

    if not data:
        raise HTTPException(status_code=500, detail="AI Analysis failed")

    return data

@router.websocket("/product_chat")
async def product_chat(
    websocket: WebSocket,
    product_id: int,
    product_sku_id: Optional[str] = None,
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
                await websocket.send_json({"event": event, "data": data})
    except WebSocketDisconnect:
        pass