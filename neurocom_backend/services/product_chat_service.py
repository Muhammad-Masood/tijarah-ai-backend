"""
Conversational agent for questions about ONE Daraz product — reviews/ratings,
catalog details, and orders (especially returns).

Architecture: a LangGraph tool-calling agent (langchain.agents.create_agent,
the current non-deprecated replacement for langgraph.prebuilt.create_react_agent)
with four tools, each a closure bound to the requesting merchant's access
token and the product being discussed — the LLM never sees or chooses the
access token, and never needs to pass product_id/product_sku_id itself,
which keeps it from wandering into other products' data.

Tool outputs are trimmed/flattened rather than returning raw Daraz payloads:
those are deeply nested with dozens of fields most of which are irrelevant
to a chat answer, and every extra field is tokens spent on every single
turn (not just once) since the whole message history is resent on each
LLM call. Keeping tool results compact is what keeps a multi-turn
conversation affordable and fast.

Streaming: stream_product_chat_response yields (event, data) pairs — same
convention as utils/sse.py's SSE pipelines — but delivered over the
WebSocket connection in reviews_router.product_chat rather than as SSE
frames, so a client sees the answer token-by-token instead of waiting for
the whole (possibly multi-tool-call) turn to finish.

Memory: each WebSocket connection gets its own MemorySaver-backed thread, so
follow-up questions ("what about the second one?") resolve correctly within
a session. MemorySaver keeps state in this process's memory only — it does
not survive a restart and is not shared across worker processes, which is
fine for a single chat session's lifetime but is the thing to swap out
(e.g. a Postgres/Redis checkpointer) before running multiple backend
workers behind a load balancer.
"""

from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from neurocom_backend.services.daraz_service import (
    get_product_by_id,
    get_all_reverse_orders_info,
    get_order_by_id,
    scrape_product_reviews,
    _epoch_to_datetime,
)
from neurocom_backend.models.daraz_model import DarazProduct, ReverseOrderInfo, ScrapedProductReviewsResponse


# ---------------------------------------------------------------------------
# Tool-output trimming — keep only what's useful for a chat answer
# ---------------------------------------------------------------------------

def _format_product_summary(product: DarazProduct) -> dict:
    prices = [sku.price for sku in product.skus if sku.price is not None]
    stock = sum(sku.Available or 0 for sku in product.skus)
    description = product.attributes.description or product.attributes.short_description or ""
    return {
        "item_id": product.item_id,
        "title": product.attributes.name or product.attributes.name_en,
        "brand": product.attributes.brand,
        "status": product.status,
        "price_range": {"min": min(prices), "max": max(prices)} if prices else None,
        "total_stock": stock,
        "sku_count": len(product.skus),
        "description": description[:1000],
    }


def _format_reviews_summary(scraped: ScrapedProductReviewsResponse, max_reviews: int = 25) -> dict:
    return {
        "average_rating": scraped.average_rating,
        "total_reviews": scraped.total_reviews,
        "reviews": [
            {"rating": r.rating, "content": r.content, "date": r.review_date}
            for r in scraped.reviews[:max_reviews]
        ],
    }


def _format_return_record(order: ReverseOrderInfo) -> dict:
    lines = []
    for line in order.data.reverseOrderLineDTOList:
        return_dt = _epoch_to_datetime(line.return_order_line_gmt_create)
        lines.append({
            "reason": line.reason_text,
            "status": line.reverse_status,
            "is_disputed": line.is_dispute,
            "refund_amount": round(line.refund_amount / 100, 2),
            "return_date": return_dt.date().isoformat() if return_dt else None,
        })
    return {
        "reverse_order_id": order.data.reverse_order_id,
        "trade_order_id": order.data.trade_order_id,
        "request_type": order.data.request_type,
        "lines": lines,
    }


def _format_order_summary(order: dict) -> dict:
    return {
        "order_id": order.get("order_id"),
        "created_at": order.get("created_at"),
        "statuses": order.get("statuses"),
        "price": order.get("price"),
        "payment_method": order.get("payment_method"),
        "items": [
            {
                "name": item.get("name"),
                "sku_id": item.get("sku_id"),
                "status": item.get("status"),
                "item_price": item.get("item_price"),
                "paid_price": item.get("paid_price"),
                "tracking_code": item.get("tracking_code"),
                "reason": item.get("reason"),
            }
            for item in order.get("items", [])
        ],
    }


def _product_url(product_id: int, product_sku_id: Optional[str]) -> str:
    # scrape_product_reviews only needs the -i{item_id}(-s{sku_id})? segment
    # to resolve the item id (see daraz_service._ITEM_ID_RE) — the title
    # slug Daraz's real URLs carry isn't required.
    if product_sku_id:
        return f"https://www.daraz.pk/products/-i{product_id}-s{product_sku_id}.html"
    return f"https://www.daraz.pk/products/-i{product_id}.html"


# ---------------------------------------------------------------------------
# Tools — closures bound to one merchant/product so the LLM can't stray
# outside the conversation's scope
# ---------------------------------------------------------------------------

def build_product_chat_tools(access_token: str, product_id: int, product_sku_id: Optional[str] = None) -> list:
    @tool
    def get_product_info() -> dict:
        """Get this product's catalog details: title, brand, status, price range, total stock, and description."""
        try:
            product = get_product_by_id(product_id, access_token)
            return _format_product_summary(product.data)
        except Exception as e:
            return {"error": f"Could not fetch product info: {e}"}

    @tool
    def get_product_reviews_summary() -> dict:
        """Get this product's customer reviews and star ratings (full history, not just recent)."""
        try:
            scraped = scrape_product_reviews(_product_url(product_id, product_sku_id))
            return _format_reviews_summary(scraped)
        except Exception as e:
            return {"error": f"Could not fetch reviews: {e}"}

    @tool
    def get_product_returns(start_date: Optional[str] = None, end_date: Optional[str] = None) -> list:
        """Get return/refund records for this product, optionally scoped to a date range
        (start_date/end_date as YYYY-MM-DD). Each record includes the return reason, refund
        amount, dispute status, and a trade_order_id — pass that trade_order_id to
        get_order_details to see what was originally ordered on that order."""
        try:
            orders = get_all_reverse_orders_info(access_token, product_id, product_sku_id, start_date, end_date)
            return [_format_return_record(o) for o in orders]
        except Exception as e:
            return {"error": f"Could not fetch returns: {e}"}

    @tool
    def get_order_details(order_id: str) -> dict:
        """Get a specific order's details and line items by order id — e.g. the
        trade_order_id returned by get_product_returns."""
        try:
            order = get_order_by_id(order_id, access_token)
            return _format_order_summary(order)
        except Exception as e:
            return {"error": f"Could not fetch order {order_id}: {e}"}

    return [get_product_info, get_product_reviews_summary, get_product_returns, get_order_details]


_SYSTEM_PROMPT = (
    "You are a Daraz seller-support assistant helping a merchant understand ONE specific "
    "product — your tools are already scoped to it, so never ask the user for a product id "
    "or sku id. Answer questions about its reviews/ratings, catalog details, and orders, "
    "especially returns: when asked about returns, call get_product_returns first, then use "
    "the trade_order_id on any record of interest with get_order_details to see what was "
    "originally ordered. Cite concrete numbers from the tools rather than guessing, and say "
    "plainly when the data available doesn't answer the question."
)


def build_product_chat_agent(access_token: str, product_id: int, product_sku_id: Optional[str] = None):
    tools = build_product_chat_tools(access_token, product_id, product_sku_id)
    llm = ChatOpenAI(temperature=0, model="gpt-4o", streaming=True)
    return create_agent(llm, tools, system_prompt=_SYSTEM_PROMPT, checkpointer=MemorySaver())


async def stream_product_chat_response(agent, thread_id: str, user_message: str):
    """Yields (event, data) pairs: 'tool_start'/'tool_end' as the agent calls
    tools, 'token' for each streamed text delta, 'done' at the end of the
    turn. A mid-turn exception becomes a final 'error' event instead of
    crashing the connection, mirroring utils/sse.py's sse_stream."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield "token", {"content": content}
            elif kind == "on_tool_start":
                yield "tool_start", {"name": event.get("name"), "input": event["data"].get("input")}
            elif kind == "on_tool_end":
                output = event["data"].get("output")
                yield "tool_end", {"name": event.get("name"), "output": getattr(output, "content", output)}
        yield "done", {}
    except Exception as exc:
        yield "error", {"detail": str(exc)}
