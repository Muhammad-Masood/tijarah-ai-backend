import json
import os
from typing import Annotated, NamedTuple
from urllib.parse import urlencode

from cryptography.fernet import InvalidToken
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import RedirectResponse

from neurocom_backend.models.shopify_model import (
    ShopifyGetAllCategoriesResponse,
    ShopifyGetAllCollectionsResponse,
    ShopifyGetAllOrdersResponse,
    ShopifyGetAllProductsResponse,
    ShopifyGetProductResponse,
    ShopifyProductCreate,
)
from neurocom_backend.services.shopify_service import (
    SHOPIFY_SCOPES,
    create_new_product,
    decode_shopify_credentials,
    get_access_token,
    get_all_categories,
    get_all_collections,
    get_all_orders,
    get_all_products,
    get_product_by_id,
    get_subcategories,
    normalize_shop,
)
from neurocom_backend.utils.security import decrypt_value

_: bool = load_dotenv()

router = APIRouter(prefix="/shopify", tags=["Shopify"])


class ShopifyCredentials(NamedTuple):
    shop: str
    access_token: str


def get_shopify_credentials(
    x_shopify_access_token: Annotated[str, Header()],
) -> ShopifyCredentials:
    encrypted_token = x_shopify_access_token.strip()
    if not encrypted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Shopify access token",
        )
    try:
        decrypted = decrypt_value(encrypted_token)
        shop, access_token = decode_shopify_credentials(decrypted)
        return ShopifyCredentials(shop=shop, access_token=access_token)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encrypted Shopify credentials",
        )


@router.get("/")
async def root():
    return {"message": "Shopify Backend Server"}


@router.get("/get_auth_code")
async def auth_code(shop: str):
    if not shop.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shop domain is required",
        )

    params = {
        "client_id": os.getenv("SHOPIFY_API_KEY"),
        "scope": SHOPIFY_SCOPES,
        "redirect_uri": os.getenv("SHOPIFY_APP_CALLBACK_URL"),
    }
    auth_url = f"https://{normalize_shop(shop)}/admin/oauth/authorize?" + urlencode(params)
    print("auth_url: ", auth_url)
    return RedirectResponse(url=auth_url)


@router.get("/get_access_token")
async def access_token(code: str, shop: str):
    return get_access_token(code, shop)


@router.get("/get_all_products", response_model=ShopifyGetAllProductsResponse)
def all_products(
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetAllProductsResponse:
    return get_all_products(credentials.shop, credentials.access_token)


@router.get("/get_product_by_id", response_model=ShopifyGetProductResponse)
def product_by_id(
    product_id: str,
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetProductResponse:
    return get_product_by_id(credentials.shop, credentials.access_token, product_id)


@router.post("/create_new_product")
def new_product(
    product: ShopifyProductCreate,
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
):
    return create_new_product(credentials.shop, credentials.access_token, product)


@router.get("/get_all_orders", response_model=ShopifyGetAllOrdersResponse)
def all_orders(
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetAllOrdersResponse:
    return get_all_orders(credentials.shop, credentials.access_token)


@router.get("/get_all_categories", response_model=ShopifyGetAllCategoriesResponse)
def all_categories(
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetAllCategoriesResponse:
    return get_all_categories(credentials.shop, credentials.access_token)


@router.get("/get_subcategories/{category_id}", response_model=ShopifyGetAllCategoriesResponse)
def subcategories(
    category_id: str,
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetAllCategoriesResponse:
    return get_subcategories(credentials.shop, credentials.access_token, category_id)


@router.get("/get_all_collections", response_model=ShopifyGetAllCollectionsResponse)
def all_collections(
    credentials: ShopifyCredentials = Depends(get_shopify_credentials),
) -> ShopifyGetAllCollectionsResponse:
    return get_all_collections(credentials.shop, credentials.access_token)
