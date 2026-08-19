from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
# from mcp.client.streamable_http import streamablehttp_client
# from mcp import ClientSession
import asyncio
from starlette.responses import JSONResponse, Response
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from neurocom_backend.services.order_service import delete_order_by_id
from neurocom_backend.database.connection import get_session
from uuid import UUID
from neurocom_backend.database.models.order import Order, OrderStatus

mcp = FastMCP("Customer Support MCP Server")  

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

@mcp.tool()
def cancel_customer_order(order_id: UUID) -> str:
    """Cancel or delete the order of a customer"""
    with next(get_session()) as db:
        deleted_order = delete_order_by_id(order_id=order_id, db=db)
    return deleted_order.id

@mcp.resource("user://secret")
def your_secret() -> str:
    """Return your secret"""
    return "The secret is hidden in 5678 1234 5678 1234"

transport = SseServerTransport("/messages/")

async def handle_sse(request):
    try:
    # Prepare bidirectional streams over SSE
        async with transport.connect_sse(
            request.scope,
            request.receive,
            request._send
        ) as streams:
            # Run the MCP server: read JSON-RPC from in_stream, write replies to out_stream
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options()
            )
        print("MCP Server is Running with SSE...")
        return Response()
    except Exception as e:
        print(f"Error handling SSE: ", e)

sse_app = Starlette(
    routes=[
        Route("/sse", handle_sse, methods=["GET"]),
        # Note the trailing slash to avoid 307 redirects
        Mount("/messages/", app=transport.handle_post_message)
    ]
)

# if __name__ == "__main__":
#     mcp.run()