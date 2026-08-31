from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import FastAPI, Request, Header, UploadFile, File, Body, APIRouter, Depends, HTTPException, status, WebSocket, WebSocketException
from neurocom_backend.services.daraz_service import lazop_client, get_access_token, get_all_products, get_auth_code, create_new_product, get_category_attributes, migrate_images, get_migrated_images,migrate_image, get_all_categories, get_category_children, get_category_by_id, get_all_orders, get_all_orders_full, trace_order_by_id, get_product_reviews, get_all_reverse_orders_info, get_order_logistic_details, payout_statement, get_orders_with_items, get_order_by_id, get_all_products_reviews, scrape_product_reviews, get_reverse_orders_history, get_returns_insights, get_returns_insights_stream, get_returns_dashboard, get_product_by_id, get_conversations_sessions
from neurocom_backend.utils.security import decrypt_value
from neurocom_backend.utils.sse import sse_stream
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
from neurocom_backend.models.daraz_model import DarazProductCreate, DarazGetAllProductsResponse, DarazCategoryAttributesResponse, ReverseOrderInfo, ScrapedProductReviewsResponse, OrdersWithItemsResponse, ReturnsInsightsResponse, ReturnsDashboardResponse, DarazGetProductResponse, OrderWithItems, CatalogSearchRequest, ProductHuntRequest, CatalogSearchResponse, ProductHuntResponse
from pydantic import BaseModel, model_validator
from typing import Annotated, Optional, Any, List
import os
import json
import logging
from urllib.parse import urlencode
from dotenv import load_dotenv
from cryptography.fernet import InvalidToken
from sqlmodel import Session, select
from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.marketplace import Marketplace, MarketplaceConnection
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.dependencies import get_current_user, get_current_user_ws
from neurocom_backend.services.daraz_catalog_service import scrape_products_by_category, hunt_products_for_niche


def _resolve_daraz_access_token(
    encrypted_token: str,
    db: Session,
    merchant: Merchant,
) -> str:
    token = encrypted_token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Daraz access token",
        )
    connection = db.exec(
        select(MarketplaceConnection)
        .join(Marketplace)
        .where(
            MarketplaceConnection.merchant_id == merchant.id,
            Marketplace.slug == "daraz",
            MarketplaceConnection.encrypted_access_token == token,
        )
    ).first()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Daraz connection is not active for the authenticated merchant",
        )
    try:
        return decrypt_value(token)
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted Daraz access token",
        )


def get_daraz_access_token(
    x_daraz_access_token: Annotated[str, Header()],
    db: Annotated[Session, Depends(get_session)],
    current_user: Annotated[Merchant, Depends(get_current_user)],
) -> str:
    return _resolve_daraz_access_token(x_daraz_access_token, db, current_user)


def get_daraz_access_token_ws(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_session)],
    merchant: Annotated[Merchant, Depends(get_current_user_ws)],
) -> str:
    encrypted_token = websocket.headers.get("x-daraz-access-token", "")
    try:
        return _resolve_daraz_access_token(encrypted_token, db, merchant)
    except HTTPException as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc.detail),
        ) from exc

_:bool = load_dotenv()

router  = APIRouter(prefix="/daraz",tags=["Daraz"])
logger = logging.getLogger(__name__)

@router.get('/')
async def root():
    return {"message": "Daraz Backend Server"}

# https://api.daraz.pk/oauth/authorize?spm=a2o9m.11193531.0.0.97802891wGBXMU&response_type=code&force_auth=true&redirect_uri=https://evolvebitx.netlify.app/callback&client_id=504082
# https://api.daraz.pk/oauth/authorize?spm=a2o9m.11193531.0.0.97802891wGBXMU&response_type=code&force_auth=true&redirect_uri=https://tijarah-ai-web.vercel.app/daraz/callback&client_id=504082
@router.get('/get_auth_code')
async def auth_code():
    params = {
        "response_type": "code",
        "force_auth": "true",
        "redirect_uri": os.getenv("APP_CALLBACK_URL"),
        "client_id": os.getenv("DARAZ_APP_KEY"),
    }

    auth_url = "https://api.daraz.pk/oauth/authorize?" + urlencode(params)
    return RedirectResponse(url=auth_url)

@router.get('/get_access_token')
async def access_token(code: str):
    return get_access_token(code)

@router.get('/get_all_products', response_model=DarazGetAllProductsResponse)
def all_products(access_token: str = Depends(get_daraz_access_token)) -> DarazGetAllProductsResponse:
    return get_all_products(access_token)

@router.get('/get_product_by_id', response_model=DarazGetProductResponse)
def product_by_id(product_id: int, access_token: str = Depends(get_daraz_access_token)) -> DarazGetAllProductsResponse:
    return get_product_by_id(product_id, access_token)

@router.get('/get_all_product_reviews')
def all_products_reviews( access_token: str = Depends(get_daraz_access_token)):
    return get_all_products_reviews(access_token)

@router.get('/get_product_reviews')
def product_reviews(item_id: str, access_token: str = Depends(get_daraz_access_token)):
    return get_product_reviews(item_id, access_token)

@router.get('/scrape_product_reviews', response_model=ScrapedProductReviewsResponse)
def scraped_product_reviews(product_url: str):
    return scrape_product_reviews(product_url)

@router.get('/get_all_categories')
async def all_categories():
    return get_all_categories()

@router.get('/get_category_by_id')
async def category_by_id(category_id: int):
    return get_category_by_id(category_id)

@router.get('/get_category_children')
async def category_children(categoty_id: int):
    return get_category_children(categoty_id)

@router.get('/get_category_attributes')
async def category_attributes(
    primary_category_id: str,
    language_code: str = "en_US",
    access_token: str = Depends(get_daraz_access_token),
):
    response = get_category_attributes(primary_category_id, access_token, language_code)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="Daraz returned an invalid category-attributes response")
    code = str(response.get("code", ""))
    if code != "0":
        logger.warning(
            "Daraz category attributes rejected: category_id=%s response=%s",
            primary_category_id,
            json.dumps(response, default=str),
        )
        raise HTTPException(
            status_code=422,
            detail={"message": response.get("message") or "Could not load Daraz category attributes", "daraz_response": response},
        )
    return response


class MigrateImageRequest(BaseModel):
    storage_path: Optional[str] = None
    image_url: Optional[str] = None

    @model_validator(mode="after")
    def require_source(self):
        if not self.storage_path and not self.image_url:
            raise ValueError("storage_path or image_url is required")
        return self


@router.post('/migrate_image')
async def migrate_single_image(
    payload: MigrateImageRequest,
    merchant: Merchant = Depends(get_current_user),
    access_token: str = Depends(get_daraz_access_token),
):
    print("payload: ", payload)
    if payload.storage_path:
        path = payload.storage_path.strip().lstrip("/")
        if not path.startswith(f"{merchant.id}/") or ".." in path.split("/"):
            raise HTTPException(status_code=403, detail="Storage path does not belong to the authenticated merchant")
    response = migrate_image(
        access_token,
        image_url=payload.image_url,
        storage_path=payload.storage_path.strip().lstrip("/") if payload.storage_path else None,
    )
    data = response.get("data")
    image = data.get("image") if isinstance(data, dict) else None
    migrated_url = image.get("url") if isinstance(image, dict) else None
    code = str(response.get("code", ""))
    if code != "0" or not isinstance(migrated_url, str) or not migrated_url.startswith(("https://", "http://")):
        message = response.get("message") or response.get("detail") or response.get("code")
        raise HTTPException(
            status_code=422 if code in {"302", "303", "301"} else 502,
            detail=f"Daraz image migration failed ({code or 'unknown'}): {message or 'no migrated URL returned'}",
        )
    return {
        "image_url": migrated_url,
        "hash_code": image.get("hash_code"),
        "request_id": response.get("request_id"),
    }

@router.post('/migrate_images')
async def migrate_all_images(images_urls: list[str], access_token: str = Depends(get_daraz_access_token)):
    return migrate_images(access_token, images_urls)

@router.get("/migrate_images/result")
async def migrate_images_result(batch_id: str, access_token: str = Depends(get_daraz_access_token)):
    return get_migrated_images(access_token, batch_id)

@router.post('/create_new_product')
async def new_product(product:dict = Body(...), access_token: str = Depends(get_daraz_access_token)):
    response = create_new_product(access_token, product)
    if not isinstance(response, dict):
        raise HTTPException(status_code=502, detail="Daraz returned an invalid product creation response")
    data = response.get("data")
    item_id = data.get("item_id") if isinstance(data, dict) else None
    code = str(response.get("code", ""))
    if code != "0" or item_id is None:
        message = response.get("message") or response.get("detail") or "product was not created"
        diagnostic = response.get("detail") or response.get("errors") or response.get("data")
        logger.warning(
            "Daraz product creation rejected: code=%s request_id=%s diagnostic=%s",
            code,
            response.get("request_id"),
            json.dumps(diagnostic, default=str) if diagnostic is not None else "none",
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Daraz product creation failed ({code or 'unknown'}): {message}",
                "daraz_code": code or None,
                "daraz_message": message,
                "daraz_details": diagnostic,
                "request_id": response.get("request_id"),
            },
        )
    sku_list = data.get("sku_list") if isinstance(data, dict) else None
    first_sku = sku_list[0] if isinstance(sku_list, list) and sku_list else {}
    return {
        "item_id": str(item_id),
        "sku_id": first_sku.get("sku_id") if isinstance(first_sku, dict) else None,
        "code": code,
        "request_id": response.get("request_id"),
        "data": data,
    }

@router.get('/get_all_orders')
async def all_orders(include_canceled: bool = False, access_token: str = Depends(get_daraz_access_token)):
    return get_all_orders(access_token, include_canceled)

@router.get('/get_all_orders_full')
async def all_orders_full(
    include_canceled: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    access_token: str = Depends(get_daraz_access_token),
):
    return get_all_orders_full(access_token, include_canceled, start_date, end_date)

@router.get('/get_orders_with_items', response_model=OrdersWithItemsResponse)
async def orders_with_items(
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    access_token: str = Depends(get_daraz_access_token),
):
    return get_orders_with_items(access_token, product_sku_id, start_date, end_date)

@router.get('/get_order_by_id', response_model=OrderWithItems)
async def order_by_id(order_id: str, access_token: str = Depends(get_daraz_access_token)):
    return get_order_by_id(order_id, access_token)

@router.get('/trace_order')
async def trace_order(order_id: str, access_token: str = Depends(get_daraz_access_token)):
    return trace_order_by_id(order_id, access_token)

@router.get('/get_order_logistics_details')
async def order_logistics_details(order_id: str, access_token: str = Depends(get_daraz_access_token)):
    return get_order_logistic_details(order_id, access_token)

@router.get('/get_all_reverse_orders_info', response_model=List[ReverseOrderInfo])
async def get_reverse_orders_info(
    product_id: Optional[int] = None,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    access_token: str = Depends(get_daraz_access_token),
):
    return get_all_reverse_orders_info(access_token, product_id, product_sku_id, start_date, end_date)

@router.get('/get_reverse_order_history', response_model=Any)
async def get_reverse_order_history(reverse_order_line_id: int, access_token: str = Depends(get_daraz_access_token)):
    return get_reverse_orders_history(reverse_order_line_id, access_token)

@router.get('/returns_insights', response_model=ReturnsInsightsResponse)
async def returns_insights(
    product_id: Optional[int] = None,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    stream: bool = False,
    access_token: str = Depends(get_daraz_access_token),
):
    if stream:
        return StreamingResponse(
            sse_stream(get_returns_insights_stream(access_token, product_id, product_sku_id, start_date, end_date)),
            media_type="text/event-stream",
        )
    return get_returns_insights(access_token, product_id, product_sku_id, start_date, end_date)

@router.get('/dashboard_insights', response_model=ReturnsDashboardResponse)
async def dashboard_insights(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 10,
    access_token: str = Depends(get_daraz_access_token),
):
    return get_returns_dashboard(access_token, start_date, end_date, top_n)

@router.get('/get_payout')
async def get_payout(access_token: str = Depends(get_daraz_access_token)):
    return payout_statement(access_token)

@router.get('/conversations/sessions')
async def conversations_sessions(access_token: str = Depends(get_daraz_access_token)):
    return get_conversations_sessions(access_token)

# @router.get("/callback")
# async def callback(request: Request):
#     code = request.query_params.get("code")
#     if not code:
#         return JSONResponse({"error": "No code received"})

#     # Exchange code for access token
#     lazop_client = LazopClient("https://api.daraz.pk/rest", APP_KEY, APP_SECRET)
#     lazop_request = LazopRequest("/auth/token/create")
#     lazop_request.add_api_param("code", code)

#     response = lazop_client.execute(lazop_request)

#     return JSONResponse(response.body)


# venv\Scripts\activate
# uvicorn main:app --host 0.0.0.0 --port 8001 --reload

@router.post('/catalog/search', response_model=CatalogSearchResponse)
async def catalog_search(payload: CatalogSearchRequest):
    return scrape_products_by_category(
        query=payload.query,
        page=payload.page,
        max_pages=payload.max_pages,
        sort_by=payload.sort_by,
        price_min=payload.price_min,
        price_max=payload.price_max,
    )


@router.post('/catalog/hunt', response_model=ProductHuntResponse)
async def product_hunt(payload: ProductHuntRequest):
    print("payload: ", payload)
    return hunt_products_for_niche(
        niche=payload.niche,
        max_pages=payload.max_pages,
        min_rating=payload.min_rating,
        min_reviews=payload.min_reviews,
        max_price=payload.max_price,
    )
