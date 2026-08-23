from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import FastAPI, Request, Header, UploadFile, File, Body, APIRouter, Depends, HTTPException, status
from neurocom_backend.services.daraz_service import lazop_client, get_access_token, get_all_products, get_auth_code, create_new_product, get_category_attributes, migrate_images, get_migrated_images,migrate_image, get_all_categories, get_category_children, get_category_by_id, get_all_orders, get_all_orders_full, trace_order_by_id, get_product_reviews, get_all_reverse_orders_info, get_order_logistic_details, payout_statement, get_orders_with_items, get_all_products_reviews, scrape_product_reviews, get_reverse_orders_history, get_returns_insights, get_returns_dashboard
from neurocom_backend.utils.security import decrypt_value
from fastapi.responses import RedirectResponse, JSONResponse
from neurocom_backend.models.daraz_model import DarazProductCreate, DarazGetAllProductsResponse, ReverseOrderInfo, ScrapedProductReviewsResponse, OrdersWithItemsResponse, ReturnsInsightsResponse, ReturnsDashboardResponse
from typing import Annotated, Optional, Any, List
import os
from urllib.parse import urlencode
from dotenv import load_dotenv
from cryptography.fernet import InvalidToken


def get_daraz_access_token(
    x_daraz_access_token: Annotated[str, Header()],
) -> str:
    encrypted_token = x_daraz_access_token.strip()
    if not encrypted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Daraz access token",
        )
    try:
        return decrypt_value(encrypted_token)
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted Daraz access token",
        )

_:bool = load_dotenv()

router  = APIRouter(prefix="/daraz",tags=["Daraz"])

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
async def category_attributes(category_id: str):
    return get_category_attributes(category_id)

@router.post('/migrate_image')
async def migrate_single_image(image_url: str = Body(..., embed=True), access_token: str = Depends(get_daraz_access_token)):
    return migrate_image(access_token, image_url)

@router.post('/migrate_images')
async def migrate_all_images(images_urls: list[str], access_token: str = Depends(get_daraz_access_token)):
    return migrate_images(access_token, images_urls)

@router.get("/migrate_images/result")
async def migrate_images_result(batch_id: str, access_token: str = Depends(get_daraz_access_token)):
    return get_migrated_images(access_token, batch_id)

@router.post('/create_new_product')
async def new_product(product:dict = Body(...), access_token: str = Depends(get_daraz_access_token)):
    return create_new_product(access_token, product)

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
    access_token: str = Depends(get_daraz_access_token),
):
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