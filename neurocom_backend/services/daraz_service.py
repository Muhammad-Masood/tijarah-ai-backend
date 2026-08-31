from neurocom_backend.python.lazop.base import LazopClient, LazopRequest
import os
import re
import requests
from dotenv import load_dotenv
import logging
from fastapi import HTTPException
import json
from xml.sax.saxutils import escape
from neurocom_backend.models.daraz_model import (
    DarazGetProductResponse,
    DarazProductCreate,
    DarazGetAllProductsResponse,
    DarazProduct,
    DarazCategoryAttributesResponse,
    ReverseOrderInfo,
    ScrapedProductReview,
    ScrapedProductReviewsResponse,
    _html_to_text,
)
from neurocom_backend.services.storage_service import (
    download_product_image,
    parse_supabase_object_path,
)
from typing import Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import concurrent.futures
from neurocom_backend.utils.redis_cache import get_or_refresh, fingerprint

_:bool = load_dotenv()
logger = logging.getLogger(__name__)


lazop_client = LazopClient("https://api.daraz.pk/rest", os.getenv("DARAZ_APP_KEY"), os.getenv("DARAZ_APP_SECRET"))

def get_auth_code():
    pass

def get_access_token(code: str):
    access_token_request = LazopRequest("/auth/token/create")
    access_token_request.add_api_param("code", code)
    access_token_response = lazop_client.execute(access_token_request)
    print("Auth access token: ", access_token_response.body)
    access_token = access_token_response.body["access_token"]
    return access_token

# Daraz stamps every response with a fresh request_id / _trace_id_ even when
# the underlying product data hasn't changed at all. If we cached/compared
# those, the background revalidation would treat *every* call as "changed"
# and re-run the (expensive) cleanup below on every single request. They're
# call metadata, not product data, so they're dropped before hashing/caching.
_VOLATILE_ENVELOPE_KEYS = ("request_id", "_trace_id_")

def _fetch_all_products_raw(access_token: str) -> dict:
    """Live call to Daraz. Cheap-ish (one HTTP round trip) but returns the
    raw body as-is (HTML descriptions, volatile metadata included minus the
    always-different request_id/_trace_id_ keys) so change-detection can
    hash it without paying for HTML cleanup first."""
    all_products_request = LazopRequest("/products/get",'GET')
    all_products_request.add_api_param("offset", "0")
    all_products_request.add_api_param("limit", "50")
    all_products_request.add_api_param('filter', 'all')
    all_products_response = lazop_client.execute(all_products_request, access_token)
    print("Products: ", all_products_response.body)
    body = all_products_response.body
    if isinstance(body, str):
        body = json.loads(body)
    for key in _VOLATILE_ENVELOPE_KEYS:
        body.pop(key, None)
    return body

def _fetch_product_by_id_raw(product_id: int, access_token: str) -> dict:
    product_request = LazopRequest("/product/item/get",'GET')
    product_request.add_api_param("item_id", str(product_id))
    product_response = lazop_client.execute(product_request, access_token)
    print("Products: ", product_response.body)
    body = product_response.body
    if isinstance(body, str):
        body = json.loads(body)
    for key in _VOLATILE_ENVELOPE_KEYS:
        body.pop(key, None)
    return body

def _clean_all_products_payload(raw_body: dict) -> dict:
    """Expensive step (BeautifulSoup HTML->text cleanup + full model
    validation). Only called when the raw payload's hash has actually
    changed since the last cache write — see get_or_refresh."""
    _enrich_primary_category_names(raw_body)
    validated = DarazGetAllProductsResponse.model_validate(raw_body)
    return validated.model_dump(mode="json")

def get_all_products(access_token: str) -> DarazGetAllProductsResponse:
    print("access_token: ", access_token)
    cache_key = f"daraz:products:{fingerprint(access_token)}"
    body = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_all_products_raw(access_token),
        transform_fn=_clean_all_products_payload,
    )
    _enrich_primary_category_names(body)
    print("pr res: ", DarazGetAllProductsResponse.model_validate(body))
    return DarazGetAllProductsResponse.model_validate(body)

def get_product_by_id(product_id: int, access_token: str) -> DarazGetProductResponse:
    body = _fetch_product_by_id_raw(product_id, access_token)
    _enrich_primary_category_names(body)
    return DarazGetProductResponse.model_validate(body)

def get_all_products_reviews(access_token: str):
    all_products = get_all_products(access_token)

    product_list: list[DarazProduct] = all_products.data.products
    print(f"Fetching reviews for {len(product_list)} products: ")
    all_reviews = []

    def fetch_reviews(product: DarazProduct):
        item_id = product.item_id
        if not item_id:
            return None
        try:
             reviews = get_product_reviews(item_id, access_token)
             return {
                "product": product,
                "reviews": reviews
            }
        except Exception as e:
            print(f"Error fetching reviews for item {item_id}: {e}")
            return {
                "product": product,
                "reviews": []
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_reviews, p) for p in product_list]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                all_reviews.append(result)
    return [review for review in all_reviews if review["reviews"]]

def get_time_range(days=7):
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)

    return (
        int(start_time.timestamp() * 1000),
        int(end_time.timestamp() * 1000)
    )
    
def _fetch_product_reviews_raw(product_id: str, access_token: str) -> list:
    # start_time, end_time = get_time_range(days=9)
    # print(start_time, end_time)
    start_time = 1786690800
    end_time = 1786863600
    product_reviews_request = LazopRequest("/review/seller/history/list",'GET')
    product_reviews_request.add_api_param('item_id', product_id)
    product_reviews_request.add_api_param('start_time', start_time)
    product_reviews_request.add_api_param('end_time', end_time)
    product_reviews_request.add_api_param('current', '1')
    product_reviews_response = lazop_client.execute(product_reviews_request, access_token)
    data = product_reviews_response.body["data"]
    print("Product reviews history data: ", data)
    id_list = data.get("id_list", None)
    if id_list is None:
      print("No reviews found")
      return []
    print("ID LIST: ", id_list)
    reviews_request = LazopRequest('/review/seller/list/v2','GET')
    reviews_request.add_api_param('id_list', json.dumps(id_list))
    reviews_response = lazop_client.execute(reviews_request, access_token)
    print("Reviews response: ",reviews_response.body)
    return reviews_response.body["data"]["review_list"]

def get_product_reviews(product_id: str, access_token: str):
    cache_key = f"daraz:product_reviews:{product_id}:{fingerprint(access_token)}"
    return get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_product_reviews_raw(product_id, access_token),
        enable_background_refresh=False,
    )

# ---------------------------------------------------------------------------
# Scraping a product's *full* review history from its storefront URL.
#
# The seller API used by get_product_reviews only returns reviews within a
# rolling 7-day window (start_time/end_time on /review/seller/history/list).
# Daraz's product page itself, however, pulls its review widget from a
# public, unauthenticated JSON endpoint with no such limit and proper
# pagination metadata, so we call that directly instead of driving a
# headless browser: https://my.daraz.pk/pdp/review/getReviewList
# ---------------------------------------------------------------------------

_DARAZ_REVIEW_LIST_URL = "https://my.daraz.pk/pdp/review/getReviewList"
_ITEM_ID_RE = re.compile(r"[/-]i(\d+)(?:-s\d+)?\.html")

def _extract_item_id_from_url(product_url: str) -> str:
    match = _ITEM_ID_RE.search(product_url)
    if not match:
        raise ValueError(f"Could not extract item id from Daraz product URL: {product_url}")
    return match.group(1)

_MAX_REVIEW_PAGES = 200

def _fetch_all_scraped_reviews_raw(item_id: str) -> dict:
    page_size = 50
    all_items: list = []
    ratings: dict = {}

    # Daraz's own `paging.totalPages`/`ratings.reviewCount` count reviews
    # that never actually come back through pagination (e.g. hidden/pending
    # ones), so an empty page is the only reliable stop condition here
    # rather than trusting those totals; the page cap is just a safety net
    # against an unexpected always-non-empty response.
    for page_no in range(1, _MAX_REVIEW_PAGES + 1):
        response = requests.get(
            _DARAZ_REVIEW_LIST_URL,
            params={"itemId": item_id, "pageSize": page_size, "filter": 0, "sort": 0, "pageNo": page_no},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        model = body.get("model") or {}
        items = model.get("items") or []
        if not items:
            break
        all_items.extend(items)
        ratings = model.get("ratings") or ratings

    return {
        "item_id": item_id,
        "items": all_items,
        "total_reviews": len(all_items),
        "average_rating": ratings.get("average"),
    }

def _clean_scraped_reviews_payload(raw: dict) -> dict:
    validated = ScrapedProductReviewsResponse.model_validate({
        "item_id": raw["item_id"],
        "total_reviews": raw["total_reviews"],
        "average_rating": raw["average_rating"],
        "reviews": raw["items"],
    })
    return validated.model_dump(mode="json")

def scrape_product_reviews(product_url: str) -> ScrapedProductReviewsResponse:
    item_id = _extract_item_id_from_url(product_url)
    cache_key = f"daraz:scraped_reviews:{item_id}"
    body = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_all_scraped_reviews_raw(item_id),
        transform_fn=_clean_scraped_reviews_payload,
        enable_background_refresh=False,
    )
    return ScrapedProductReviewsResponse.model_validate(body)

def get_category_attributes(category_id: str, access_token: str, language_code: str = "en_US"):
    request = LazopRequest("/category/attributes/get", "GET")
    request.add_api_param("primary_category_id", category_id)
    request.add_api_param("language_code", language_code)
    response = lazop_client.execute(request, access_token)
    body = response.body
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="Daraz returned an invalid category-attributes response") from exc
    return body
  
from functools import lru_cache

@lru_cache(maxsize=1)
def get_all_categories():
    request = LazopRequest("/category/tree/get", "GET")
    response = lazop_client.execute(request)
    return response.body["data"]

def find_category(categories, category_id: int):
    for category in categories:
        if int(category["category_id"]) == category_id:
            return category
        if "children" in category and category["children"]:
            result = find_category(category["children"], category_id)
            if result:
                return result
    return None


@lru_cache(maxsize=1)
def _category_name_lookup() -> dict[int, str]:
    lookup: dict[int, str] = {}

    def walk(nodes: list) -> None:
        for node in nodes:
            category_id = node.get("category_id")
            name = node.get("name")
            if category_id is not None and name:
                lookup[int(category_id)] = str(name)
            children = node.get("children") or []
            if children:
                walk(children)

    walk(get_all_categories())
    return lookup


def _enrich_primary_category_names(body: dict) -> None:
    lookup = _category_name_lookup()
    data = body.get("data")
    if not isinstance(data, dict):
        return

    def set_name(product: dict) -> None:
        category_id = product.get("primary_category")
        if category_id is not None:
            product["primary_category_name"] = lookup.get(int(category_id))

    products = data.get("products")
    if isinstance(products, list):
        for product in products:
            if isinstance(product, dict):
                set_name(product)
    elif "primary_category" in data:
        set_name(data)


def get_category_by_id(category_id: int):
    all_categories = get_all_categories()
    return find_category(all_categories, category_id)
      
def get_category_children(category_id: int):
    all_categories_request = LazopRequest("/category/tree/get", "GET")
    response = lazop_client.execute(all_categories_request)

    all_categories_tree = response.body
    if isinstance(all_categories_tree, str):
        all_categories_tree = json.loads(all_categories_tree)

    categories = all_categories_tree.get("data", [])

    def find_category(categories, category_id):
        for category in categories:
            # FIX: Daraz uses "category_id", not "id"
            if int(category["category_id"]) == category_id:
                return category.get("children", [])
            children = category.get("children", [])
            if children:
                found = find_category(children, category_id)
                if found is not None:
                    return found
        return None

    return find_category(categories, category_id) or []


_DARAZ_MAX_IMAGE_BYTES = 1 * 1024 * 1024
# Daraz /image/migrate only fetches whitelisted external URLs (SSRF-safe CDN
# list). Supabase and most seller-hosted storage are rejected with E302.
_DARAZ_MIGRATE_HOST_SUFFIXES = (
    ".slatic.net",
    ".alicdn.com",
)


def _is_daraz_migrate_supported_url(image_url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(image_url).hostname or "").lower()
    return any(host.endswith(suffix) for suffix in _DARAZ_MIGRATE_HOST_SUFFIXES)


def _content_type_to_filename(content_type: str, fallback_url: str) -> str:
    ext = { "image/jpeg": ".jpg", "image/png": ".png" }.get(content_type.lower())
    if ext:
        return f"product{ext}"
    from urllib.parse import urlparse

    path = urlparse(fallback_url).path
    name = path.rsplit("/", 1)[-1] if path else "product.jpg"
    return name if name.lower().endswith((".jpg", ".jpeg", ".png")) else "product.jpg"


def _validate_daraz_image(content: bytes, content_type: str, filename: str) -> tuple[bytes, str]:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in {"image/jpeg", "image/png"}:
        raise HTTPException(
            status_code=415,
            detail="Daraz accepts only JPEG and PNG images (1 MB max). Re-upload as JPG or PNG.",
        )
    if len(content) > _DARAZ_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds Daraz 1 MB limit")
    return content, _content_type_to_filename(normalized, filename)


def _download_image_for_daraz(image_url: str) -> tuple[bytes, str]:
    try:
        response = requests.get(image_url, timeout=(10, 30))
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not download image: {exc}") from exc

    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    content = response.content
    if not content:
        raise HTTPException(status_code=400, detail="Downloaded image is empty")
    return _validate_daraz_image(content, content_type, image_url)


def _load_image_for_daraz(*, image_url: str | None, storage_path: str | None) -> tuple[bytes, str]:
    if storage_path:
        content, content_type = download_product_image(storage_path)
        return _validate_daraz_image(content, content_type, storage_path)

    if not image_url:
        raise HTTPException(status_code=400, detail="storage_path or image_url is required")

    supabase_path = parse_supabase_object_path(image_url)
    if supabase_path:
        content, content_type = download_product_image(supabase_path)
        return _validate_daraz_image(content, content_type, supabase_path)

    return _download_image_for_daraz(image_url)


def _parse_daraz_image_response(body: Any) -> dict:
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Daraz returned an invalid image response")
    return body


def upload_image(access_token: str, image_bytes: bytes, filename: str = "product.jpg") -> dict:
    """Upload image bytes via Daraz /image/upload (local upload)."""
    if len(image_bytes) > _DARAZ_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds Daraz 1 MB limit")

    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif lower.endswith(".png"):
        content_type = "image/png"
    else:
        raise HTTPException(status_code=415, detail="Daraz accepts only JPEG and PNG images")

    request = LazopRequest("/image/upload")
    print(filename, image_bytes, content_type)
    request.add_file_param("image", image_bytes)
    print("request in upload_image: ", request)
    response = lazop_client.execute(request, access_token)
    print("response: ", response)
    return _parse_daraz_image_response(response.body)


def migrate_image(
    access_token: str,
    *,
    image_url: str | None = None,
    storage_path: str | None = None,
) -> dict:
    """Return a Daraz-hosted image URL for product create/update.

    Prefer storage_path for Supabase uploads (private buckets). Whitelisted
    external URLs use /image/migrate; everything else is uploaded via
    /image/upload after server-side download.
    """
    if storage_path or not image_url or not _is_daraz_migrate_supported_url(image_url):
        image_bytes, filename = _load_image_for_daraz(image_url=image_url, storage_path=storage_path)
        return upload_image(access_token, image_bytes, filename)

    request = LazopRequest("/image/migrate")
    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<Request>
    <Image>
        <Url>{escape(image_url)}</Url>
    </Image>
</Request>"""

    print("xml_payload: ", xml_payload)
    request.add_api_param("payload", xml_payload)
    response = lazop_client.execute(request, access_token)
    print("response: ", response)
    body = _parse_daraz_image_response(response.body)
    print("body: ", body)
    if str(body.get("code", "")) == "302":
        image_bytes, filename = _load_image_for_daraz(image_url=image_url, storage_path=storage_path)
        return upload_image(access_token, image_bytes, filename)
    return body    
def migrate_images(access_token: str, images_urls: list[str]):
  
  image_urls = [
    "https://fakestoreapi.com/img/71li-ujtlUL._AC_UX679_t.png",
    "https://fakestoreapi.com/img/71YXzeOuslL._AC_UY879_t.png"
    ]
  request = LazopRequest('/images/migrate')
  
  xml_payload = """
  <?xml version="1.0" encoding="UTF-8" ?>
<Request>
    <Images>
        <Url>https://fakestoreapi.com/img/71li-ujtlUL._AC_UX679_t.png</Url>
        <Url>https://fakestoreapi.com/img/71YXzeOuslL._AC_UY879_t.png</Url>
    </Images>
</Request>
  """
  request.add_api_param("payload", xml_payload)
  response = lazop_client.execute(request, access_token)
  print(response)
  if isinstance(response.body, dict):
        return response.body
  else:
    return json.loads(response.body)
  
def get_migrated_images(access_token: str, batch_id: str):
    request = LazopRequest('/image/response/get', 'GET')
    request.add_api_param('batch_id', batch_id)
    response = lazop_client.execute(request, access_token)
    print(response)
    if isinstance(response.body, dict):
        return response.body
    return json.loads(response.body)


# Operational fields that always live on <Sku>, never in product <Attributes>.
_SKU_OPERATIONAL_FIELDS: frozenset[str] = frozenset({
    "SellerSku", "quantity", "price", "special_price", "special_from_date", "special_to_date",
    "package_length", "package_width", "package_height", "package_weight", "package_content",
})
_STANDARD_SKU_FIELDS: frozenset[str] = frozenset({
    "SellerSku", "quantity", "price", "special_price", "special_from_date", "special_to_date",
    "package_length", "package_height", "package_weight", "package_width", "package_content", "Images",
})


def _is_valid_xml_tag_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _extract_sku_extra_fields(sku: dict) -> dict[str, str]:
    return {
        name: str(value)
        for name, value in sku.items()
        if name not in _STANDARD_SKU_FIELDS
        and value not in (None, "")
        and _is_valid_xml_tag_name(name)
    }


def _parse_category_attribute_sets(body: Any) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return (sale_prop_names, sku_attribute_names, product_attribute_names)."""
    if not isinstance(body, dict):
        return frozenset(), frozenset(), frozenset()
    sale_props: set[str] = set()
    sku_attrs: set[str] = set()
    product_attrs: set[str] = set()
    for attr in body.get("data") or []:
        name = attr.get("name")
        if not name:
            continue
        if int(attr.get("is_sale_prop") or 0) == 1:
            sale_props.add(name)
        elif attr.get("attribute_type") == "sku":
            sku_attrs.add(name)
        else:
            product_attrs.add(name)
    return frozenset(sale_props), frozenset(sku_attrs), frozenset(product_attrs)


def _load_category_attribute_sets(
    category_id: Any,
    access_token: str,
    *,
    category_body: dict | None = None,
) -> tuple[frozenset[str], frozenset[str], frozenset[str], dict]:
    body = category_body
    if body is None:
        try:
            body = get_category_attributes(str(category_id), access_token)
        except Exception:
            logger.warning("Could not load category attributes for %s", category_id, exc_info=True)
            body = {}
    if isinstance(body, dict):
        sale_props, sku_attrs, product_attrs = _parse_category_attribute_sets(body)
        if sale_props or sku_attrs or product_attrs:
            return sale_props, sku_attrs, product_attrs, body
    return frozenset({"size"}), frozenset(), frozenset({"color_family", "color"}), body or {}


_SIZE_CHART_ATTR_NAMES: frozenset[str] = frozenset({"size_chart", "Size_Chart_Image"})


def _category_requires_size_chart(category_body: dict, sale_prop_names: frozenset[str]) -> bool:
    for attr in category_body.get("data") or []:
        if attr.get("name") in _SIZE_CHART_ATTR_NAMES:
            return True
    return "size" in sale_prop_names


def _is_daraz_hosted_image_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host.endswith((".daraz.pk", ".daraz.com")) or host.endswith(".slatic.net") or "lazada" in host


def _extract_migrated_image_url(response: dict) -> str | None:
    data = response.get("data")
    image = data.get("image") if isinstance(data, dict) else None
    url = image.get("url") if isinstance(image, dict) else None
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return url
    return None


def _resolve_daraz_image_url(
    access_token: str,
    *,
    image_url: str | None = None,
    storage_path: str | None = None,
) -> str:
    if storage_path:
        response = migrate_image(access_token, storage_path=storage_path)
    elif image_url:
        if _is_daraz_hosted_image_url(image_url):
            return image_url
        response = migrate_image(access_token, image_url=image_url)
    else:
        raise HTTPException(status_code=422, detail="size_chart image URL or storage path is required")

    migrated_url = _extract_migrated_image_url(response)
    if migrated_url:
        return migrated_url
    message = response.get("message") or response.get("detail") or response.get("code")
    raise HTTPException(
        status_code=502,
        detail=f"Daraz image migration failed for size chart: {message or 'no migrated URL returned'}",
    )


def _ensure_size_chart(
    access_token: str,
    product_attributes: dict[str, Any],
    skus: list[dict],
    *,
    category_body: dict,
    sale_prop_names: frozenset[str],
    product: dict,
) -> None:
    if not _category_requires_size_chart(category_body, sale_prop_names):
        return

    chart_url = (
        product_attributes.get("size_chart")
        or product_attributes.get("Size_Chart_Image")
        or product.get("size_chart")
        or product.get("size_chart_url")
    )
    chart_storage_path = product.get("size_chart_storage_path") or product_attributes.get("size_chart_storage_path")
    if not chart_url and not chart_storage_path and skus:
        chart_url = skus[0].get("Size_Chart_Image") or skus[0].get("size_chart")
        chart_storage_path = skus[0].get("size_chart_storage_path")

    if not chart_url and not chart_storage_path:
        raise HTTPException(
            status_code=422,
            detail=(
                "Size chart image is required for this Daraz category. "
                "Provide Attributes.size_chart, Skus[].Size_Chart_Image, or size_chart_url on the publish payload."
            ),
        )

    daraz_url = _resolve_daraz_image_url(
        access_token,
        image_url=str(chart_url) if chart_url else None,
        storage_path=str(chart_storage_path) if chart_storage_path else None,
    )
    product_attributes["size_chart"] = daraz_url
    if skus:
        skus[0]["Size_Chart_Image"] = daraz_url


def _collect_sale_props_by_name(
    skus: list[dict],
    *,
    sale_prop_names: frozenset[str],
) -> dict[str, set[str]]:
    by_name: dict[str, set[str]] = {}
    for sku in skus:
        for name, value in _extract_sku_extra_fields(sku).items():
            if name in sale_prop_names:
                by_name.setdefault(name, set()).add(value)
    return by_name


def _sale_prop_order(names: set[str]) -> list[str]:
    priority = {"color_family": 0, "size": 1}
    return sorted(names, key=lambda n: (priority.get(n, 2), n))


_IMAGE_CAPABLE_SALE_PROPS: frozenset[str] = frozenset({"color_family", "color"})


def _build_variation_xml(sale_props_by_name: dict[str, set[str]], *, sku_has_images: bool) -> str:
    if not sale_props_by_name:
        return ""
    blocks: list[str] = []
    for idx, name in enumerate(_sale_prop_order(set(sale_props_by_name)), start=1):
        options = sorted(sale_props_by_name[name])
        has_image = (
            idx == 1
            and name in _IMAGE_CAPABLE_SALE_PROPS
            and sku_has_images
        )
        options_xml = "".join(f"<option>{escape(opt)}</option>" for opt in options)
        blocks.append(
            f"<Variation{idx}>"
            f"<name>{escape(name)}</name>"
            f"<hasImage>{'true' if has_image else 'false'}</hasImage>"
            f"<customize>false</customize>"
            f"<options>{options_xml}</options>"
            f"</Variation{idx}>"
        )
    return f"<variation>{''.join(blocks)}</variation>"


def _build_sale_prop_xml(sale_props: dict[str, str], *, prop_order: list[str]) -> str:
    if not sale_props:
        return ""
    ordered = [name for name in prop_order if name in sale_props]
    ordered.extend(name for name in sorted(sale_props) if name not in ordered)
    inner = "".join(f"<{name}>{escape(sale_props[name])}</{name}>" for name in ordered)
    return f"<saleProp>{inner}</saleProp>"


def _daraz_response_detail(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if detail in (None, "", []):
        return None
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or detail)
    return str(detail)


def _normalize_create_product_payload(
    product: dict,
    *,
    migrate_to_sku_names: frozenset[str],
) -> dict:
    """Move category SKU fields out of Attributes and into Sku rows."""
    attrs = dict(product.get("Attributes") or {})
    skus = [dict(sku) for sku in (product.get("Skus") or [])]
    if not skus:
        raise HTTPException(status_code=422, detail="At least one SKU is required")

    for field in migrate_to_sku_names:
        value = attrs.pop(field, None)
        if value in (None, ""):
            continue
        for sku in skus:
            if sku.get(field) in (None, ""):
                sku[field] = value

    for sku in skus:
        package_content = sku.get("package_content")
        if isinstance(package_content, str) and package_content:
            sku["package_content"] = _html_to_text(package_content)

    attrs.pop("title", None)
    return {**product, "Attributes": attrs, "Skus": skus}


_COLOR_PRODUCT_FIELDS: frozenset[str] = frozenset({"color_family", "color"})


def _promote_product_attributes(
    product_attributes: dict[str, Any],
    skus: list[dict],
    product_attr_names: frozenset[str],
) -> None:
    """Copy values from Sku rows onto product Attributes when Daraz expects them there."""
    promote_names = set(product_attr_names) | _COLOR_PRODUCT_FIELDS
    for name in promote_names:
        if product_attributes.get(name) not in (None, ""):
            continue
        for sku in skus:
            value = sku.get(name)
            if value not in (None, ""):
                product_attributes[name] = value
                break


def create_new_product(access_token: str, product: Any):
  create_product_request = LazopRequest('/product/create')
  product_dict = dict(product)
  sale_prop_names, sku_attr_names, product_attr_names, category_body = _load_category_attribute_sets(
      product_dict.get("PrimaryCategory"),
      access_token,
  )
  migrate_to_sku_names = _SKU_OPERATIONAL_FIELDS | sale_prop_names | sku_attr_names
  product = _normalize_create_product_payload(product_dict, migrate_to_sku_names=migrate_to_sku_names)
  title = str(product.get("Title") or "").strip()
  if not title:
      raise HTTPException(status_code=422, detail="Product title is required")

  first_sku = product["Skus"][0]
  package_fallback = str(first_sku.get("package_content") or "")
  brand = str(product["Attributes"].get("brand") or "No Brand").strip()
  if brand.lower() in {"no", "none", "no brand"}:
      brand = "No Brand"
  product_attributes = {
        **product["Attributes"],
        "name": title,
        "name_en": str(product["Attributes"].get("name_en") or title),
        "short_description": str(product["Attributes"].get("short_description") or package_fallback),
        "description": str(product["Attributes"].get("description") or package_fallback),
        "warranty_type": str(product["Attributes"].get("warranty_type") or "No Warranty"),
        "brand": brand,
  }
  if not str(product_attributes.get("model") or "").strip():
      product_attributes["model"] = "General"
  skus = [dict(sku) for sku in product["Skus"]]
  _promote_product_attributes(product_attributes, skus, product_attr_names)
  _ensure_size_chart(
      access_token,
      product_attributes,
      skus,
      category_body=category_body,
      sale_prop_names=sale_prop_names,
      product=product_dict,
  )
  exclude_from_product_attrs = _SKU_OPERATIONAL_FIELDS | sale_prop_names | sku_attr_names
  attributes_xml = "".join([
        f"<{attr_name}>{escape(str(attr_value))}</{attr_name}>"
        for attr_name, attr_value in product_attributes.items()
        if attr_value is not None and attr_value != ""
        and attr_name not in exclude_from_product_attrs
        and _is_valid_xml_tag_name(attr_name)
  ])
  images_xml = "".join([f"<Image>{escape(str(img))}</Image>" for img in product["Images"]])
  sale_props_by_name = _collect_sale_props_by_name(skus, sale_prop_names=sale_prop_names)
  sale_prop_order = _sale_prop_order(set(sale_props_by_name))
  sku_has_images = any(sku.get("Images") for sku in skus)
  sku_images_enabled = bool(sale_prop_names & _IMAGE_CAPABLE_SALE_PROPS)
  variation_xml = _build_variation_xml(sale_props_by_name, sku_has_images=sku_has_images)
  skus_xml = ""
  for sku in skus:
    sku_images_xml = ""
    if sku_images_enabled:
        sku_images_xml = "".join([
            f"<Image>{escape(str(img))}</Image>" for img in sku.get("Images", [])
        ])
    extra_fields = _extract_sku_extra_fields(sku)
    sale_props = {name: value for name, value in extra_fields.items() if name in sale_prop_names}
    sku_attrs_xml = "".join(
        f"<{name}>{escape(value)}</{name}>"
        for name, value in sorted(
            (name, value) for name, value in extra_fields.items() if name in sku_attr_names
        )
    )
    sale_props_xml = _build_sale_prop_xml(sale_props, prop_order=sale_prop_order)
    skus_xml += f"""
        <Sku>
            <SellerSku>{escape(str(sku['SellerSku']))}</SellerSku>
            {sku_attrs_xml}
            {sale_props_xml}
            <quantity>{sku['quantity']}</quantity>
            <price>{sku['price']}</price>
            <package_length>{sku['package_length']}</package_length>
            <package_height>{sku['package_height']}</package_height>
            <package_weight>{sku['package_weight']}</package_weight>
            <package_width>{sku['package_width']}</package_width>
            <package_content>{escape(str(sku['package_content']))}</package_content>
            {f"<Images>{sku_images_xml}</Images>" if sku_images_xml else ""}
        </Sku>
        """
  xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Request>
      <Product>
        <PrimaryCategory>{product["PrimaryCategory"]}</PrimaryCategory>
        <SPUId/>
        <AssociatedSku/>
        <Images>{images_xml}</Images>
        {variation_xml}
        <Attributes>{attributes_xml}</Attributes>
        <Skus>{skus_xml}</Skus>
      </Product>
    </Request>"""
    
  logger.info(
      "Daraz create payload: category_id=%s title_length=%s attributes=%s sku_fields=%s sale_props=%s sku_attrs=%s product_attrs=%s image_count=%s",
      product["PrimaryCategory"],
      len(title),
      sorted(product_attributes),
      sorted(product["Skus"][0]) if product["Skus"] else [],
      sorted(sale_prop_names),
      sorted(sku_attr_names),
      sorted(product_attr_names),
      len(product["Images"]),
  )
  print("xml_payload: ", xml_payload)
  create_product_request.add_api_param('payload', xml_payload)
  response = lazop_client.execute(create_product_request, access_token)
  if response.code and str(response.code) != "0":
      body = response.body if isinstance(response.body, dict) else {}
      logger.error(
          "Daraz product/create failed: code=%s message=%s detail=%s request_id=%s",
          response.code,
          response.message,
          _daraz_response_detail(body),
          response.request_id,
      )
  if isinstance(response.body, dict):
      return response.body
  try:
      return json.loads(response.body)
  except (TypeError, json.JSONDecodeError) as exc:
      raise HTTPException(status_code=502, detail="Daraz returned an invalid product creation response") from exc
  
    #  <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
    #           <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
    # <brand>Remark</brand>
              
# def create_new_product(access_token: str, product: DarazProductCreate):
#     create_product_request = LazopRequest('/product/create')
#     xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
#         <Request>
#           <Product>
#             <PrimaryCategory>{product.PrimaryCategory}</PrimaryCategory>
#             <SPUId/>
#             <AssociatedSku/>
#             <Images>
#               {''.join([f'<Image>{img}</Image>' for img in product.Images])}
#             </Images>
#             <Attributes>
#               <name>{product.name}</name>
#               <short_description>{product.short_description}</short_description>
#               <short_description_en>{product.short_description}</short_description_en>
#               <description>{product.description}</description>
#               <description_en>{product.description}</description_en>
#               <brand>{product.brand}</brand>
#               <model>asdf</model>
#               <kid_years>Kids (6-10yrs)</kid_years>
#               <name_en>{product.name}</name_en>
#               <occasion>Casual</occasion>
#               <age_range>Standard</age_range>
#               <warranty_type>No Warranty</warranty_type>
#             </Attributes>
#             <Skus>
#               <Sku>
#                 <SellerSku>api-create-test-2</SellerSku>
#                 <color_family>Green</color_family>
#                 <size>40</size>
#                 <quantity>1</quantity>
#                 <price>389</price>
#                 <package_length>11</package_length>
#                 <package_height>22</package_height>
#                 <package_weight>33</package_weight>
#                 <package_width>44</package_width>
#                 <package_content>this is what's in the box</package_content>
#                 <Images>
#                   <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
#                   <Image>https://static-01.daraz.pk/p/97545b9b42e3a4781ff7c98c68002352.png</Image>
#                 </Images>
#               </Sku>
#             </Skus>
#           </Product>
#         </Request>"""
        
#     create_product_request.add_api_param('payload', xml_payload)
#     response = lazop_client.execute(create_product_request, access_token)
#     return JSONResponse({"type": response.type, "body": response.body})


def get_all_orders(access_token: str, include_canceled: bool = False):
    all_orders_request = LazopRequest("/orders/get",'GET')
    all_orders_request.add_api_param("offset", "0")
    all_orders_request.add_api_param("limit", "10")
    all_orders_request.add_api_param("sort_by", "updated_at")
    all_orders_request.add_api_param('sort_direction', 'DESC')
    all_orders_request.add_api_param('created_after', '2017-02-10T09:00:00+08:00')
    all_orders_response = lazop_client.execute(all_orders_request, access_token)
    print("Orders: ", all_orders_response.body)
    data = all_orders_response.body["data"]
    if not include_canceled:
        orders = [o for o in data.get("orders", []) if "canceled" not in o.get("statuses", [])]
        data = {**data, "orders": orders, "count": len(orders)}
    return data

# ---------------------------------------------------------------------------
# get_all_orders only returns a single page (limit=10) — countTotal in that
# response can be in the thousands, and /orders/get's offset param doesn't
# reliably support paging deep enough to walk a seller's whole history. So
# instead of offset, this walks forward through time: page ascending by
# created_at, then re-issue the request with created_after advanced past
# the last order in the page, until the running total reaches countTotal.
# ---------------------------------------------------------------------------

def _advance_created_after(created_at: str) -> str:
    """Daraz's created_at *response* field looks like
    '2026-08-20 16:32:40 +0800'; the created_after *request* param instead
    expects '2026-08-20T16:32:40+08:00' (matches the seed value used by
    get_all_orders). Bumped by one second so the boundary order — the last
    one in the page just fetched — isn't re-fetched forever."""
    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S %z") + timedelta(seconds=1)
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S%z")  # e.g. ...+0800
    return f"{iso[:-2]}:{iso[-2:]}"  # -> ...+08:00

def _fetch_all_orders_raw(access_token: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list:
    page_size = 100
    created_after = f"{start_date}T00:00:00+08:00" if start_date else '2017-02-10T09:00:00+08:00'
    created_before = f"{end_date}T23:59:59+08:00" if end_date else None
    all_orders: list = []
    seen_order_ids: set = set()
    count_total = None

    while True:
        request = LazopRequest("/orders/get", 'GET')
        request.add_api_param("offset", "0")
        request.add_api_param("limit", str(page_size))
        request.add_api_param("sort_by", "created_at")
        request.add_api_param("sort_direction", "ASC")
        request.add_api_param("created_after", created_after)
        if created_before:
            request.add_api_param("created_before", created_before)
        response = lazop_client.execute(request, access_token)
        print("Orders page: ", response.body)
        data = response.body["data"]
        orders = data.get("orders", [])
        if count_total is None:
            count_total = data.get("countTotal", len(orders))

        new_orders = [o for o in orders if o["order_id"] not in seen_order_ids]
        if not new_orders:
            break
        seen_order_ids.update(o["order_id"] for o in new_orders)
        all_orders.extend(new_orders)

        if len(all_orders) >= count_total:
            break

        created_after = _advance_created_after(orders[-1]["created_at"])

    return all_orders

def get_all_orders_full(
    access_token: str,
    include_canceled: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    cache_key = f"daraz:all_orders_full:{fingerprint(access_token)}:{start_date or 'any'}:{end_date or 'any'}"
    all_orders = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_all_orders_raw(access_token, start_date, end_date),
        enable_background_refresh=False,
    )
    orders = all_orders if include_canceled else [
        o for o in all_orders if "canceled" not in o.get("statuses", [])
    ]
    return {"orders": orders, "count": len(orders)}

def get_order_detail(order_id: str, access_token: str):
    order_detail_request = LazopRequest('/order/items/get','GET')
    order_detail_request.add_api_param('order_id', order_id)
    order_detail_response = lazop_client.execute(order_detail_request, access_token)
    print("Order detail: ", order_detail_response.body)
    return order_detail_response.body
  
def get_orders_details(order_ids: list[str], access_token: str):
  print("Order IDs: ", order_ids)
  orders_details_request = LazopRequest('/orders/items/get','GET')
  orders_details_request.add_api_param('order_ids', f"{order_ids}")
  orders_details_response = lazop_client.execute(orders_details_request, access_token)
  print("Orders details: ", orders_details_response.body)
  return orders_details_response.body["data"]

def get_order_by_id(order_id: str, access_token: str) -> dict:
    """Single-order counterpart to get_orders_with_items: /order/get for the
    order header, merged with its line items from get_orders_details (the
    same /orders/items/get batch endpoint used everywhere else in this
    file, just called with a single order_id)."""
    order_request = LazopRequest('/order/get', 'GET')
    order_request.add_api_param('order_id', order_id)
    order_response = lazop_client.execute(order_request, access_token)
    print("Order: ", order_response.body)
    order = order_response.body["data"]

    numeric_order_id = order["order_id"]
    details = get_orders_details([numeric_order_id], access_token)
    order_items = next(
        (d["order_items"] for d in details if d["order_id"] == numeric_order_id),
        []
    )
    return {**order, "items": order_items}

_ORDER_DETAILS_BATCH_SIZE = 50

def _fetch_orders_with_items_raw(access_token: str, start_date: Optional[str], end_date: Optional[str]) -> list:
    orders_res = get_all_orders_full(access_token, start_date=start_date, end_date=end_date)
    orders = orders_res.get("orders", [])
    if not orders:
        return []
    print("Orders: ", orders[0]["order_id"], type(orders[0]["order_id"]))
    order_ids = [int(o["order_id"]) for o in orders]
    print(order_ids)

    # /orders/items/get doesn't document a max batch size; chunk defensively
    # since get_all_orders_full can return thousands of orders where the old
    # single-page get_all_orders (limit 10) never could.
    details: list = []
    for i in range(0, len(order_ids), _ORDER_DETAILS_BATCH_SIZE):
        batch = order_ids[i:i + _ORDER_DETAILS_BATCH_SIZE]
        details.extend(get_orders_details(batch, access_token))

    merged_orders = []
    for order in orders:
        order_id = order["order_id"]
        order_items = next(
            (d["order_items"] for d in details if d["order_id"] == order_id),
            []
        )
        merged_orders.append({
            **order,
            "items": order_items
        })

    return merged_orders

def get_orders_with_items(
    access_token: str,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    cache_key = f"daraz:orders_with_items:{fingerprint(access_token)}:{start_date or 'any'}:{end_date or 'any'}"
    merged_orders = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_orders_with_items_raw(access_token, start_date, end_date),
        enable_background_refresh=False,
    )

    if product_sku_id is not None:
        merged_orders = [
            order for order in merged_orders
            if any(str(item.get("sku_id")) == str(product_sku_id) for item in order.get("items", []))
        ]

    return {"orders": merged_orders, "count": len(merged_orders)}
  
# def get_order_logistic_details(order_id: str, access_token: str):
#   order_logistic_request = LazopRequest('/order/logistic/get')
#   order_logistic_request.add_api_param('order_id', order_id)
#   order_logistic_request.add_api_param('package_id_list', '[]')
#   order_logistic_request.add_api_param('locale', 'en')
#   order_logistic_response = lazop_client.execute(order_logistic_request, access_token)
#   print("Order Logistic Details: ", order_logistic_response.body)
#   order_tracking_number = order_logistic_response.body["data"]["module"][0]["package_detail_info_list"][0].get("tracking_number", None)
#   if(order_tracking_number is None):
#     print("No tracking number found")
#     return {}
#   order_package_history_request = LazopRequest("/logistics/epis/packages/history",'GET')
#   order_package_history_request.add_api_param('includeTimeline', 'true')
#   order_package_history_request.add_api_param('trackingNumber', order_tracking_number)
#   order_package_history_response = lazop_client.execute(order_package_history_request)
#   print("Package history details: ", order_package_history_response.body)
#   return order_package_history_response.body

def get_order_logistic_details(order_id: str, access_token: str):
    # Step 1: Fetch logistic details
    order_logistic_request = LazopRequest('/order/logistic/get')
    order_logistic_request.add_api_param('order_id', order_id)
    order_logistic_request.add_api_param('package_id_list', '[]')
    order_logistic_request.add_api_param('locale', 'en')

    order_logistic_response = lazop_client.execute(order_logistic_request, access_token)
    print("Order Logistic Details: ", order_logistic_response.body)

    try:
        # body = json.loads(order_logistic_response.body)
        modules = order_logistic_response.body.get("data", {}).get("module", [])
        print("Modules: ", modules)
        if not modules:
            print("No modules found in logistic details")
            return {}

        package_list = modules[0].get("packageDetailInfoList", [])
        if not package_list:
            print("No package details found")
            return {}

        order_tracking_number = package_list[0].get("trackingNumber")
        print("Tracking Number: ", order_tracking_number)
        if not order_tracking_number:
            print("No tracking number found")
            return {}

    except Exception as e:
        print("Error parsing logistic response:", e)
        return {}

    # Step 2: Fetch package history
    order_package_history_request = LazopRequest("/logistics/epis/packages/history", 'GET')
    order_package_history_request.add_api_param('includeTimeline', 'true')
    order_package_history_request.add_api_param('trackingNumber', order_tracking_number)

    order_package_history_response = lazop_client.execute(order_package_history_request, access_token)
    print("Package history details: ", order_package_history_response.body)

    # Return parsed JSON instead of raw string (optional)
    try:
        return json.loads(order_package_history_response.body)
    except:
        return {"raw": order_package_history_response.body}

def trace_order_by_id(order_id: str, access_token: str):
    trace_order_request = LazopRequest("/logistic/order/trace",'GET')
    # trace_order_request = LazopRequest("/logistics/epis/packages/history",'GET')
    trace_order_request.add_api_param("order_id", order_id)
    trace_order_request.add_api_param('locale', 'en')
    trace_order_request.add_api_param('ofcPackageIdList', '[]')
    track_order_response = lazop_client.execute(trace_order_request, access_token)
    print("Track Order Data: ", track_order_response.body)
    return track_order_response.body

def _date_to_epoch_millis(date_str: str, end_of_day: bool = False) -> int:
    time_part = "23:59:59" if end_of_day else "00:00:00"
    dt = datetime.strptime(f"{date_str} {time_part}", "%Y-%m-%d %H:%M:%S")
    return int(dt.timestamp() * 1000)

def get_reverse_orders(access_token: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    page_no = 1
    page_size = 100
    all_items = []
    total = None

    while total is None or page_size * (page_no - 1) < total:
        reverse_orders_request = LazopRequest("/reverse/getreverseordersforseller", 'GET')
        reverse_orders_request.add_api_param('page_no', str(page_no))
        reverse_orders_request.add_api_param('page_size', str(page_size))
        if start_date:
            reverse_orders_request.add_api_param('ReverseOrderLineTimeRangeStart', str(_date_to_epoch_millis(start_date)))
        if end_date:
            reverse_orders_request.add_api_param('ReverseOrderLineTimeRangeEnd', str(_date_to_epoch_millis(end_date, end_of_day=True)))
        reverse_orders_response = lazop_client.execute(reverse_orders_request, access_token)
        print("Reverse orders: ", reverse_orders_response.body)
        result = reverse_orders_response.body["result"]
        total = result["total"]
        all_items.extend(result["items"])
        page_no += 1

    return [item for item in all_items if item.get("request_type") != "CANCEL"]

def get_reverse_order_info(reverse_order_id: str, access_token: str):
    reverse_order_request = LazopRequest("/order/reverse/return/detail/list",'GET')
    reverse_order_request.add_api_param('reverse_order_id', reverse_order_id)
    reverse_order_response = lazop_client.execute(reverse_order_request, access_token)
    print("Reverse orders info: ", reverse_order_response.body)
    return reverse_order_response.body

def get_reverse_orders_history(reverse_order_line_id: int, access_token: str):
    reverse_order_request = LazopRequest("/order/reverse/return/history/list",'GET')
    reverse_order_request.add_api_param('reverse_order_line_id', str(reverse_order_line_id))
    reverse_order_request.add_api_param('page_size', '10')
    reverse_order_request.add_api_param('page_number', '1')
    reverse_order_response = lazop_client.execute(reverse_order_request, access_token)
    print("Reverse orders history info: ", reverse_order_response.body)
    return reverse_order_response.body

def _fetch_all_reverse_orders_info_raw(access_token: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list:
  reverse_orders = get_reverse_orders(access_token, start_date, end_date)
  print("reverse orders: ", reverse_orders)
  reverse_orders_info = []
  for reverse_order in reverse_orders:
    print(reverse_order)
    info = get_reverse_order_info(reverse_order['reverse_order_id'], access_token)
    print(info)
    reverse_orders_info.append(info)
  print("reverse orders info: ",reverse_orders_info )
  return reverse_orders_info

def _clean_reverse_orders_info_payload(raw_items: list) -> list:
  return [
    ReverseOrderInfo.model_validate(item).model_dump(mode="json", by_alias=True)
    for item in raw_items
  ]

def _in_product_scope(
    candidate_product_id: Optional[int],
    candidate_sku_id: Optional[str],
    product_id: Optional[int],
    product_sku_id: Optional[str],
) -> bool:
    """Shared scoping rule used to filter both order items and reverse-order
    lines down to one product/sku. product_sku_id, when given, wins over
    product_id (it's the more specific filter) rather than requiring both to
    match — matches how callers actually use these params (pick one)."""
    if product_id is None and product_sku_id is None:
        return True
    if product_sku_id is not None:
        return candidate_sku_id is not None and str(candidate_sku_id) == str(product_sku_id)
    return candidate_product_id is not None and candidate_product_id == product_id

def get_all_reverse_orders_info(
    access_token: str,
    product_id: Optional[int] = None,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[ReverseOrderInfo]:
  cache_key = f"daraz:reverse_orders_info:{fingerprint(access_token)}:{start_date or 'any'}:{end_date or 'any'}"
  body = get_or_refresh(
    cache_key,
    fetch_raw_fn=lambda: _fetch_all_reverse_orders_info_raw(access_token, start_date, end_date),
    transform_fn=_clean_reverse_orders_info_payload,
    enable_background_refresh=False,
  )
  all_orders = [ReverseOrderInfo.model_validate(item) for item in body]
  if product_id is None and product_sku_id is None:
    return all_orders
  return [
    order for order in all_orders
    if any(
      _in_product_scope(line.productDTO.product_id, line.productDTO.sku, product_id, product_sku_id)
      for line in order.data.reverseOrderLineDTOList
    )
  ]

# ---------------------------------------------------------------------------
# Returns / reverse-order intelligence.
#
# Return rate needs two independently-fetched datasets joined on the Daraz
# item id: units *sold* (get_orders_with_items, which merges /orders/get
# with /orders/items/get) and units *returned* (get_all_reverse_orders_info,
# /order/reverse/return/detail/list). Order items don't carry a clean
# item_id field — it's the numeric prefix of shop_sku, e.g.
# "796269189_PK-3668742984" -> 796269189 — while reverse-order lines do
# (productDTO.product_id), so that prefix parse plus that field is the join
# key used throughout below.
# ---------------------------------------------------------------------------

_RETURN_REASON_HINTS = [
    (("size", "fit", "small", "large", "tight", "loose"), "Sizing mismatch — double-check size chart accuracy and consider adding a fit guide."),
    (("not as described", "different", "not match", "not same", "misleading", "not what"), "Listing doesn't match the product received — audit photos and description for accuracy."),
    (("defect", "damage", "broken", "faulty", "not working", "quality", "poor"), "Quality or packaging issue — review QC and packaging before shipment."),
    (("wrong item", "wrong product", "incorrect item", "different item"), "Fulfillment error — audit the picking/packing process for mix-ups."),
    (("late", "delay", "shipping", "delivery"), "Delivery experience issue — review courier performance and SLAs."),
    (("change of mind", "changed my mind", "no longer", "don't want", "dont want", "don't need", "dont need"), "Buyer's remorse — set clearer expectations pre-purchase to reduce impulse returns."),
    (("color", "colour"), "Color mismatch — check photo color accuracy across devices/lighting."),
    (("price", "cheaper", "found cheaper"), "Price sensitivity — monitor competitor pricing on this product."),
]

def _infer_return_recommendation(reason_text: str) -> str:
    lowered = (reason_text or "").lower()
    for keywords, recommendation in _RETURN_REASON_HINTS:
        if any(kw in lowered for kw in keywords):
            return recommendation
    return "Recurring complaint — investigate directly with affected customers to find the root cause."

def _item_id_from_shop_sku(shop_sku: Optional[str]) -> Optional[int]:
    if not shop_sku:
        return None
    prefix = shop_sku.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else None

def _epoch_to_datetime(value: Optional[int]) -> Optional[datetime]:
    if not value:
        return None
    try:
        seconds = value / 1000 if value > 10**12 else value
        return datetime.fromtimestamp(seconds)
    except (ValueError, OSError, OverflowError):
        return None

def _epoch_to_month(value: Optional[int]) -> Optional[str]:
    dt = _epoch_to_datetime(value)
    return dt.strftime("%Y-%m") if dt else None

def get_returns_insights_stream(
    access_token: str,
    product_id: Optional[int] = None,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    yield "progress", {"stage": "fetching_returns"}
    reverse_orders = get_all_reverse_orders_info(access_token, start_date=start_date, end_date=end_date)
    yield "progress", {"stage": "fetched_returns", "count": len(reverse_orders)}

    if end_date is None:
        end_date = datetime.now().date().isoformat()
    if start_date is None:
        last_reverse_order = reverse_orders[-1].data.reverseOrderLineDTOList[0].trade_order_gmt_create
        last_reverse_order_dt = datetime.fromtimestamp(last_reverse_order)
        start_date = (last_reverse_order_dt - timedelta(days=1)).date().isoformat()
        print("last_reverse_order: ", start_date)

    print(f"Fetching orders with items for {start_date} to {end_date}...")
    yield "progress", {"stage": "fetching_orders"}
    orders_res = get_orders_with_items(access_token, start_date=start_date, end_date=end_date)
    print("orders_res: ", orders_res)
    yield "progress", {"stage": "fetched_orders", "count": orders_res.get("count", 0)}
    # --- units sold, within the requested scope ---
    scoped_units_sold = 0
    for order in orders_res.get("orders", []):
        for item in order.get("items", []):
            item_product_id = _item_id_from_shop_sku(item.get("shop_sku"))
            if _in_product_scope(item_product_id, item.get("sku_id"), product_id, product_sku_id):
                scoped_units_sold += 1

    # --- returns: reason/refund/dispute stats within the requested scope ---
    reason_counter: dict = defaultdict(int)
    monthly_counter: dict = defaultdict(int)
    scoped_returns = 0
    scoped_refund_total = 0.0
    scoped_dispute_count = 0
    scoped_refund_request_count = 0

    for order in reverse_orders:
        for line in order.data.reverseOrderLineDTOList:
            if not _in_product_scope(line.productDTO.product_id, line.productDTO.sku, product_id, product_sku_id):
                continue

            scoped_returns += 1
            # refund_amount is in the smallest currency subunit (paisa);
            # /100 converts to whole rupees, matching how amounts elsewhere
            # (e.g. order price) are represented.
            scoped_refund_total += line.refund_amount / 100
            if line.is_dispute:
                scoped_dispute_count += 1
            if line.is_need_refund:
                scoped_refund_request_count += 1
            reason_counter[line.reason_text or "Unspecified"] += 1
            month = _epoch_to_month(line.return_order_line_gmt_create)
            if month:
                monthly_counter[month] += 1

    reason_breakdown = [
        {
            "reason": reason,
            "count": count,
            "percentage": round(count / scoped_returns * 100, 1) if scoped_returns else 0.0,
            "likely_cause": _infer_return_recommendation(reason),
        }
        for reason, count in sorted(reason_counter.items(), key=lambda kv: kv[1], reverse=True)
    ]

    monthly_trend = [
        {"month": month, "returns_count": count}
        for month, count in sorted(monthly_counter.items())
    ]

    overall_return_rate = round(scoped_returns / scoped_units_sold * 100, 1) if scoped_units_sold else 0.0
    dispute_rate = round(scoped_dispute_count / scoped_returns * 100, 1) if scoped_returns else 0.0
    refund_request_rate = round(scoped_refund_request_count / scoped_returns * 100, 1) if scoped_returns else 0.0

    recommendations = []
    if overall_return_rate >= 10:
        recommendations.append(
            f"Return rate is {overall_return_rate}% — above the ~5-8% norm for most categories; "
            "the reason breakdown below points at where to start."
        )
    if reason_breakdown:
        top_reason = reason_breakdown[0]
        recommendations.append(
            f"Top return reason is '{top_reason['reason']}' ({top_reason['count']} cases, "
            f"{top_reason['percentage']}%): {top_reason['likely_cause']}"
        )
    if dispute_rate >= 20:
        recommendations.append(
            f"{dispute_rate}% of returns in scope are disputed — review return-approval "
            "criteria to reduce buyer friction."
        )

    yield "complete", {
        "scope": "sku" if product_sku_id else ("product" if product_id else "store-wide"),
        "product_id": product_id,
        "product_sku_id": product_sku_id,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "total_units_sold": scoped_units_sold,
        "total_units_returned": scoped_returns,
        "overall_return_rate": overall_return_rate,
        "total_refund_amount": scoped_refund_total,
        "dispute_rate": dispute_rate,
        "refund_request_rate": refund_request_rate,
        "return_reason_breakdown": reason_breakdown,
        "monthly_trend": monthly_trend,
        "recommendations": recommendations,
    }


def get_returns_insights(
    access_token: str,
    product_id: Optional[int] = None,
    product_sku_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Non-streaming entry point — drains get_returns_insights_stream and
    returns only its final result (this is the single computation path;
    the two never drift)."""
    result = None
    for event, data in get_returns_insights_stream(access_token, product_id, product_sku_id, start_date, end_date):
        if event == "complete":
            result = data
    return result

def get_returns_dashboard(
    access_token: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 10,
) -> dict:
    """Store-wide return-rate ranking across the whole product catalog
    (get_all_products, for titles) rather than just the products that show
    up in a given order/return window — a product with zero sales and zero
    returns still shows up here, it just won't rank near the top."""
    reverse_orders = get_all_reverse_orders_info(access_token, start_date=start_date, end_date=end_date)

    if end_date is None:
        end_date = datetime.now().date().isoformat()
    if start_date is None:
        last_reverse_order = reverse_orders[-1].data.reverseOrderLineDTOList[0].trade_order_gmt_create
        last_reverse_order_dt = datetime.fromtimestamp(last_reverse_order)
        start_date = (last_reverse_order_dt - timedelta(days=1)).date().isoformat()
        print("last_reverse_order: ", start_date)

    orders_res = get_orders_with_items(access_token, start_date=start_date, end_date=end_date)
    all_products = get_all_products(access_token)
    product_titles = {
        product.item_id: (product.attributes.name_en or product.attributes.name)
        for product in all_products.data.products
    }

    units_sold_by_product: dict = defaultdict(int)
    for order in orders_res.get("orders", []):
        for item in order.get("items", []):
            item_product_id = _item_id_from_shop_sku(item.get("shop_sku"))
            if item_product_id is not None:
                units_sold_by_product[item_product_id] += 1

    # Returns are restricted to the same [start_date, end_date] window as
    # sales here (get_returns_insights doesn't do this — see its own note —
    # but a return-rate ranking is only meaningful if both sides of the
    # ratio cover the same period).
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
    returns_by_product: dict = defaultdict(int)
    refund_by_product: dict = defaultdict(float)
    for order in reverse_orders:
        for line in order.data.reverseOrderLineDTOList:
            line_dt = _epoch_to_datetime(line.return_order_line_gmt_create)
            if line_dt is None or not (start_dt <= line_dt < end_dt):
                continue
            pid = line.productDTO.product_id
            returns_by_product[pid] += 1
            refund_by_product[pid] += line.refund_amount / 100  # paisa -> rupees

    all_product_ids = set(units_sold_by_product) | set(returns_by_product) | set(product_titles)
    product_stats = []
    for pid in all_product_ids:
        sold = units_sold_by_product.get(pid, 0)
        returned = returns_by_product.get(pid, 0)
        rate = round(returned / sold * 100, 1) if sold else (100.0 if returned else 0.0)
        product_stats.append({
            "product_id": pid,
            "product_title": product_titles.get(pid),
            "units_sold": sold,
            "units_returned": returned,
            "return_rate": rate,
            "total_refund_amount": round(refund_by_product.get(pid, 0.0), 2),
        })
    product_stats.sort(key=lambda p: (p["return_rate"], p["units_returned"]), reverse=True)
    # Only rank products with enough sales volume to be a meaningful signal
    # — one sale that got returned is a 100% rate but not yet a real pattern.
    ranked_products = [p for p in product_stats if p["units_sold"] >= 3][:top_n]

    return {
        "date_range": {"start_date": start_date, "end_date": end_date},
        "top_products_by_return_rate": ranked_products,
    }

def payout_statement(access_token: str):
  request = LazopRequest('/finance/payout/status/get','GET')
  request.add_api_param('created_after', '2018-01-01')
  response = lazop_client.execute(request, access_token)
  print(response.type)
  print(response.body)
  return response.body

def get_conversations_sessions(access_token: str):
  request = LazopRequest('/im/session/list','GET')
  response = lazop_client.execute(request, access_token)
  print(response.body)
  return response.body
