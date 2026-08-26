from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, WebSocketException
from contextlib import asynccontextmanager, AsyncExitStack
from dotenv import load_dotenv
from .database.connection import perform_migration
from .routers import customer_support_router, order_router, product_router, daraz_router, shopify_router, forecast_router, reviews_router, auth_router, marketplace_router, product_chat_router
from neurocom_backend.dependencies import get_current_user
from neurocom_backend.mcp_server.customer_support.main import sse_app
from neurocom_backend.mcp_server.client import MCPClient
from starlette.routing import Host
from neurocom_backend.utils.settings import ALLOWED_ORIGINS
import ast
from fastapi.middleware.cors import CORSMiddleware

_: bool = load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # print("Performing migrations...")
    perform_migration()
    # mcp.run_sse_async("/sse")
    # mcp.streamable_http_app()   
    # mcp.session_manager.run()
    # async with AsyncExitStack() as stack:
    #     await stack.enter_async_context(mcp.session_manager.run())
    # mcp.run()
    # print("MCP server running...")
    yield

# app = FastAPI(title="Neurocom Backend", lifespan=lambda app: mcp.session_manager.run())

app = FastAPI(title="Tijarah AI Backend Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount('/mcp', sse_app)

@app.get("/")
def root():
    return {"message": "Welcome to Neurocom Backend!"}

@app.get("/health")
def read_root():
    return {"message": "MCP SSE Server is running"}


# @app.websocket('/chat')
# async def chat(websocket: WebSocket):
#     await con_manager.connect(websocket)
#     try:
#         memory = []
#         tool_context = await mcp_client.get_tool_context()
#         user_input = None
#         while True:            
#             if not user_input:
#                 user_input = await websocket.receive_text()
            
#             if user_input.lower() in ["exit", "bye", "close"]:
#                 await con_manager.broadcast("Agent: See you later!")
#                 break

#             # response = await chat_agent(user_input, memory, tool_context)
#             response = {}
#             user_input = None
#             memory.append(response["response"])
            
#             if isinstance(response, dict) and response.get("action") == "respond_to_user":
#                 message = response["response"]
#                 print("Response from Agent: " + message)                
#                 await con_manager.broadcast(f"Agent: {str(message)}")
#             else:
#                 user_input = response["response"]
#     except WebSocketDisconnect:
#         con_manager.disconnect(websocket)


require_auth = [Depends(get_current_user)]

app.include_router(auth_router.router)
# app.include_router(order_router.router, dependencies=require_auth)
# app.include_router(product_router.router, dependencies=require_auth)
app.include_router(customer_support_router.router, dependencies=require_auth)
app.include_router(daraz_router.router, dependencies=require_auth)
app.include_router(shopify_router.router, dependencies=require_auth)
app.include_router(forecast_router.router, dependencies=require_auth)
app.include_router(reviews_router.router, dependencies=require_auth)
app.include_router(marketplace_router.router, dependencies=require_auth)
# No dependencies= here: this router's websocket route does its own
# merchant-JWT auth per-route (get_current_user_ws) — see
# product_chat_router's module docstring for why require_auth
# (OAuth2PasswordBearer-based) can't be applied at include time here.
app.include_router(product_chat_router.router)