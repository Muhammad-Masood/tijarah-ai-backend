# Customer Support Router

from fastapi import WebSocket
from neurocom_backend.services.chat_service import get_chat_response_service
from fastapi import APIRouter, Depends, HTTPException
from neurocom_backend.mcp_server.client import MCPClient
from typing import Annotated
from mcp import Tool, ClientSession
# from mcp.server.fastmcp import FastMCP
# from mcp.client.streamable_http import streamablehttp_client
# from mcp import ClientSession
from fastmcp import Client
import asyncio

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            print(f"Active connection found: {connection}")
            await connection.send_text(message)

router  = APIRouter(prefix="/customer_support",tags=["Customer Support"])

sse_urls = ["http://localhost:8000/mcp/sse"]
mcp_client = MCPClient()
mcp_client._add_sse_urls(sse_urls)
connection_manager = ConnectionManager()


@router.get('/')
def home():
    return {"message": "Chat Router"}

@router.get('/get_tools')
async def get_tools(mcp_client_session: Annotated[ClientSession, Depends(mcp_client.get_session)]):
    try:
        tools = await mcp_client.get_tools(session=mcp_client_session)
        print("Tools: ", tools)
        return {"tools_context": tools}
    except Exception as e:
        raise HTTPException(status=500, detail=str(e))


@router.get('/chat/{prompt}')
async def chat(prompt: str, mcp_client_session: Annotated[ClientSession, Depends(mcp_client.get_session)]):
    try:
        chat_response = await mcp_client.process_query(query=prompt, session=mcp_client_session)
        print("Chat response: ",chat_response)
        return {"content": chat_response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
