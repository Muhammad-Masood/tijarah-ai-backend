import json
import os
from typing import Any, Optional

import requests
from fastapi import HTTPException, status

from neurocom_backend.models.shopify_model import (
    ShopifyGetAllCategoriesResponse,
    ShopifyGetAllCollectionsResponse,
    ShopifyGetAllOrdersResponse,
    ShopifyGetAllProductsResponse,
    ShopifyGetProductResponse,
    ShopifyProduct,
    ShopifyProductCreate,
    ShopifyTaxonomyCategory,
)
from neurocom_backend.utils.redis_cache import fingerprint, get_or_refresh
from neurocom_backend.utils.settings import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_CACHE_TTL_SECONDS

SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-01")
SHOPIFY_SCOPES = os.getenv(
    "SHOPIFY_SCOPES",
    "read_products,write_products,read_orders,read_inventory,write_inventory,read_publications,write_publications",
)


def normalize_shop(shop: str) -> str:
    shop = shop.strip().lower()
    shop = shop.replace("https://", "").replace("http://", "")
    shop = shop.rstrip("/")
    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
    return shop


def _graphql_url(shop: str) -> str:
    return f"https://{normalize_shop(shop)}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"


def graphql_request(
    shop: str,
    access_token: str,
    query: str,
    variables: Optional[dict] = None,
) -> dict:
    response = requests.post(
        _graphql_url(shop),
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token,
        },
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    if not response.ok:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Shopify API request failed: {response.status_code} {response.text}",
        )

    payload = response.json()
    if payload.get("errors"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"shopify_errors": payload["errors"]},
        )
    return payload.get("data") or {}


def _raise_user_errors(data: dict, *paths: str) -> None:
    for path in paths:
        node = data
        for key in path.split("."):
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            user_errors = node.get("userErrors") or []
            if user_errors:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"userErrors": user_errors},
                )


def get_access_token(code: str, shop: str) -> dict:
    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shopify API credentials are not configured",
        )

    shop = normalize_shop(shop)
    response = requests.post(
        f"https://{shop}/admin/oauth/access_token",
        json={
            "client_id": SHOPIFY_API_KEY,
            "client_secret": SHOPIFY_API_SECRET,
            "code": code,
        },
        timeout=30,
    )
    if not response.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange Shopify authorization code: {response.text}",
        )

    body = response.json()
    access_token = body.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shopify did not return an access token",
        )
    return {
        "access_token": access_token,
        "scope": body.get("scope"),
        "shop": shop,
    }


def _product_storefront_url(shop: str, node: dict) -> str | None:
    online_url = node.get("onlineStoreUrl")
    if online_url:
        return online_url
    handle = node.get("handle")
    if handle:
        return f"https://{normalize_shop(shop)}/products/{handle}"
    return None


def _flatten_product(node: dict, *, shop: str | None = None) -> dict:
    images = [
        {"src": edge["node"]["src"], "altText": edge["node"].get("altText")}
        for edge in node.get("images", {}).get("edges", [])
    ]
    variants = [
        {
            "id": edge["node"]["id"],
            "title": edge["node"]["title"],
            "price": edge["node"].get("price"),
            "inventoryQuantity": edge["node"].get("inventoryQuantity"),
        }
        for edge in node.get("variants", {}).get("edges", [])
    ]
    result = {
        "id": node["id"],
        "title": node["title"],
        "handle": node.get("handle"),
        "status": node.get("status"),
        "createdAt": node.get("createdAt"),
        "updatedAt": node.get("updatedAt"),
        "description": node.get("description"),
        "productType": node.get("productType"),
        "totalInventory": node.get("totalInventory"),
        "tags": node.get("tags") or [],
        "category": node.get("category"),
        "images": images,
        "variants": variants,
    }
    if shop:
        result["url"] = _product_storefront_url(shop, node)
    return result


def _fetch_all_products_raw(shop: str, access_token: str) -> list[dict]:
    all_products: list[dict] = []
    has_next_page = True
    cursor = None

    query = """
    query getProducts($cursor: String) {
      products(first: 250, after: $cursor) {
        edges {
          cursor
          node {
            id
            title
            handle
            onlineStoreUrl
            status
            createdAt
            updatedAt
            description
            productType
            totalInventory
            tags
            category { id name }
            images(first: 5) {
              edges { node { src altText } }
            }
            variants(first: 10) {
              edges { node { id title price inventoryQuantity } }
            }
          }
        }
        pageInfo { hasNextPage }
      }
    }
    """

    while has_next_page:
        data = graphql_request(shop, access_token, query, {"cursor": cursor})
        edges = data["products"]["edges"]
        for edge in edges:
            all_products.append(_flatten_product(edge["node"], shop=shop))
        has_next_page = data["products"]["pageInfo"]["hasNextPage"]
        cursor = edges[-1]["cursor"] if has_next_page and edges else None

    return all_products


def _clean_all_products_payload(raw_products: list[dict]) -> dict:
    validated = ShopifyGetAllProductsResponse(
        products=[ShopifyProduct.model_validate(p) for p in raw_products]
    )
    return validated.model_dump(mode="json")


def get_all_products(shop: str, access_token: str) -> ShopifyGetAllProductsResponse:
    cache_key = f"shopify:products:{fingerprint(access_token)}:{normalize_shop(shop)}"
    body = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_all_products_raw(shop, access_token),
        transform_fn=_clean_all_products_payload,
        ttl_seconds=SHOPIFY_CACHE_TTL_SECONDS,
    )
    return ShopifyGetAllProductsResponse.model_validate(body)


def get_product_by_id(shop: str, access_token: str, product_id: str) -> ShopifyGetProductResponse:
    query = """
    query ProductQuery($id: ID!) {
      product(id: $id) {
        id
        title
        handle
        onlineStoreUrl
        status
        createdAt
        updatedAt
        description
        productType
        totalInventory
        tags
        category { id name }
        images(first: 5) {
          edges { node { src altText } }
        }
        variants(first: 10) {
          edges { node { id title price inventoryQuantity } }
        }
      }
    }
    """
    data = graphql_request(shop, access_token, query, {"id": product_id})
    product = data.get("product")
    if product is None:
        return ShopifyGetProductResponse(product=None)
    return ShopifyGetProductResponse(product=ShopifyProduct.model_validate(_flatten_product(product, shop=shop)))


def get_location_id(shop: str, access_token: str) -> str:
    query = """
    query {
      locations(first: 5) {
        edges { node { id name } }
      }
    }
    """
    data = graphql_request(shop, access_token, query)
    edges = data.get("locations", {}).get("edges", [])
    if not edges:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Shopify locations found for this store",
        )
    return edges[0]["node"]["id"]


def get_online_store_publication_id(shop: str, access_token: str) -> str:
    """Return the publication GID for the Online Store sales channel."""
    query = """
    query GetPublications {
      publications(first: 50) {
        nodes {
          id
          name
          catalog { title }
        }
      }
    }
    """
    data = graphql_request(shop, access_token, query)
    for publication in data.get("publications", {}).get("nodes", []):
        name = (publication.get("name") or "").strip().lower()
        catalog_title = ((publication.get("catalog") or {}).get("title") or "").strip().lower()
        if name == "online store" or catalog_title == "online store":
            return publication["id"]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Online Store publication not found for this Shopify shop",
    )


def publish_product_to_online_store(shop: str, access_token: str, product_id: str) -> None:
    publication_id = get_online_store_publication_id(shop, access_token)
    query = """
    mutation PublishProduct($id: ID!, $input: [PublicationInput!]!) {
      publishablePublish(id: $id, input: $input) {
        publishable {
          ... on Product { id }
        }
        userErrors { field message }
      }
    }
    """
    data = graphql_request(
        shop,
        access_token,
        query,
        {"id": product_id, "input": [{"publicationId": publication_id}]},
    )
    _raise_user_errors(data, "publishablePublish")


def create_new_product(shop: str, access_token: str, product: ShopifyProductCreate) -> dict:
    location_id = get_location_id(shop, access_token)

    create_query = """
    mutation CreateProduct($input: ProductCreateInput!, $media: [CreateMediaInput!]) {
      productCreate(product: $input, media: $media) {
        product {
          id
          title
          status
          category { id }
          variants(first: 1) { nodes { id } }
        }
        userErrors { field message }
      }
    }
    """

    product_input: dict[str, Any] = {
        "title": product.title,
        "descriptionHtml": product.descriptionHtml,
        "status": "ACTIVE",
    }
    if product.vendor:
        product_input["vendor"] = product.vendor
    if product.tags:
        product_input["tags"] = product.tags
    if product.collectionsToJoin:
        product_input["collectionsToJoin"] = product.collectionsToJoin
    if product.category:
        product_input["category"] = product.category

    media = [img.model_dump(exclude_none=True) for img in (product.images or [])]

    data = graphql_request(
        shop,
        access_token,
        create_query,
        {"input": product_input, "media": media or None},
    )
    _raise_user_errors(data, "productCreate")

    created = data["productCreate"]["product"]
    product_id = created["id"]
    variant_id = created["variants"]["nodes"][0]["id"]

    bulk_update_query = """
    mutation BulkUpdateVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(
        productId: $productId
        variants: $variants
        allowPartialUpdates: true
      ) {
        productVariants { id inventoryItem { id } }
        userErrors { field message }
      }
    }
    """
    update_data = graphql_request(
        shop,
        access_token,
        bulk_update_query,
        {
            "productId": product_id,
            "variants": [{"id": variant_id, "price": product.price}],
        },
    )
    _raise_user_errors(update_data, "productVariantsBulkUpdate")

    inventory_item_id = update_data["productVariantsBulkUpdate"]["productVariants"][0][
        "inventoryItem"
    ]["id"]

    tracking_query = """
    mutation EnableTracking($inventoryItemId: ID!) {
      inventoryItemUpdate(id: $inventoryItemId, input: { tracked: true }) {
        inventoryItem { id tracked }
        userErrors { field message }
      }
    }
    """
    tracking_data = graphql_request(
        shop, access_token, tracking_query, {"inventoryItemId": inventory_item_id}
    )
    _raise_user_errors(tracking_data, "inventoryItemUpdate")

    activate_query = """
    mutation ActivateInventory($inventoryItemId: ID!, $locationId: ID!) {
      inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId) {
        inventoryLevel { id }
        userErrors { field message }
      }
    }
    """
    activate_data = graphql_request(
        shop,
        access_token,
        activate_query,
        {"inventoryItemId": inventory_item_id, "locationId": location_id},
    )
    _raise_user_errors(activate_data, "inventoryActivate")

    set_inventory_query = """
    mutation SetInventory($locationId: ID!, $inventoryItemId: ID!, $quantity: Int!) {
      inventorySetQuantities(
        input: {
          reason: "correction"
          ignoreCompareQuantity: true
          name: "available"
          quantities: [{
            locationId: $locationId
            inventoryItemId: $inventoryItemId
            quantity: $quantity
          }]
        }
      ) {
        userErrors { field message }
      }
    }
    """
    inventory_data = graphql_request(
        shop,
        access_token,
        set_inventory_query,
        {
            "locationId": location_id,
            "inventoryItemId": inventory_item_id,
            "quantity": product.inventory,
        },
    )
    _raise_user_errors(inventory_data, "inventorySetQuantities")

    publish_product_to_online_store(shop, access_token, product_id)

    return {
        "product_id": product_id,
        "variant_id": variant_id,
        "inventory_item_id": inventory_item_id,
        "title": created["title"],
        "status": created["status"],
    }


def _fetch_all_orders_raw(shop: str, access_token: str) -> list[dict]:
    all_orders: list[dict] = []
    has_next_page = True
    cursor = None

    query = """
    query getOrders($cursor: String) {
      orders(first: 100, after: $cursor, sortKey: CREATED_AT, reverse: true, query: "created_at:>=2026-08-07") {
        edges {
          cursor
          node {
            id
            name
            createdAt
            updatedAt
            processedAt
            displayFinancialStatus
            displayFulfillmentStatus
            totalPriceSet {
              shopMoney { amount currencyCode }
            }
            customer { id displayName phone }
            lineItems(first: 50) {
              edges {
                node {
                  id
                  title
                  quantity
                  originalUnitPriceSet {
                    shopMoney { amount currencyCode }
                  }
                  variant { id title }
                }
              }
            }
          }
        }
        pageInfo { hasNextPage }
      }
    }
    """

    while has_next_page:
        data = graphql_request(shop, access_token, query, {"cursor": cursor})
        edges = data["orders"]["edges"]
        for edge in edges:
            node = edge["node"]
            shop_money = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
            line_items = []
            for item_edge in node.get("lineItems", {}).get("edges", []):
                item = item_edge["node"]
                item_money = (item.get("originalUnitPriceSet") or {}).get("shopMoney") or {}
                variant = item.get("variant")
                line_items.append(
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "quantity": item["quantity"],
                        "price": item_money.get("amount"),
                        "currency": item_money.get("currencyCode"),
                        "variant": (
                            {"id": variant["id"], "title": variant.get("title")}
                            if variant
                            else None
                        ),
                    }
                )
            all_orders.append(
                {
                    "id": node["id"],
                    "name": node["name"],
                    "createdAt": node.get("createdAt"),
                    "updatedAt": node.get("updatedAt"),
                    "processedAt": node.get("processedAt"),
                    "displayFinancialStatus": node.get("displayFinancialStatus"),
                    "displayFulfillmentStatus": node.get("displayFulfillmentStatus"),
                    "totalPriceSet": node.get("totalPriceSet"),
                    "customer": node.get("customer"),
                    "lineItems": line_items,
                    "totalAmount": shop_money.get("amount"),
                    "currencyCode": shop_money.get("currencyCode"),
                }
            )
        has_next_page = data["orders"]["pageInfo"]["hasNextPage"]
        cursor = edges[-1]["cursor"] if has_next_page and edges else None

    return all_orders


def _clean_all_orders_payload(raw_orders: list[dict]) -> dict:
    return ShopifyGetAllOrdersResponse.model_validate({"orders": raw_orders}).model_dump(
        mode="json"
    )


def get_all_orders(shop: str, access_token: str) -> ShopifyGetAllOrdersResponse:
    cache_key = f"shopify:orders:{fingerprint(access_token)}:{normalize_shop(shop)}"
    body = get_or_refresh(
        cache_key,
        fetch_raw_fn=lambda: _fetch_all_orders_raw(shop, access_token),
        transform_fn=_clean_all_orders_payload,
        ttl_seconds=SHOPIFY_CACHE_TTL_SECONDS,
    )
    return ShopifyGetAllOrdersResponse.model_validate(body)


def get_all_categories(shop: str, access_token: str) -> ShopifyGetAllCategoriesResponse:
    all_categories: list[ShopifyTaxonomyCategory] = []
    has_next_page = True
    after = None

    query = """
    query getCategories($first: Int!, $after: String) {
      taxonomy {
        categories(first: $first, after: $after) {
          edges {
            node { id name fullName }
            cursor
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """

    while has_next_page:
        data = graphql_request(shop, access_token, query, {"first": 50, "after": after})
        categories = data["taxonomy"]["categories"]
        all_categories.extend(
            ShopifyTaxonomyCategory.model_validate(edge["node"]) for edge in categories["edges"]
        )
        has_next_page = categories["pageInfo"]["hasNextPage"]
        after = categories["pageInfo"]["endCursor"]
        if not has_next_page or not after:
            break

    return ShopifyGetAllCategoriesResponse(categories=all_categories)


def get_subcategories(
    shop: str, access_token: str, category_id: str
) -> ShopifyGetAllCategoriesResponse:
    all_subcategories: list[ShopifyTaxonomyCategory] = []
    has_next_page = True
    after = None

    query = """
    query getSubcategories($first: Int!, $after: String, $parentId: ID!) {
      taxonomy {
        categories(first: $first, after: $after, childrenOf: $parentId) {
          edges {
            node { id name fullName }
            cursor
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """

    while has_next_page:
        data = graphql_request(
            shop,
            access_token,
            query,
            {"first": 50, "after": after, "parentId": category_id},
        )
        categories = data["taxonomy"]["categories"]
        all_subcategories.extend(
            ShopifyTaxonomyCategory.model_validate(edge["node"]) for edge in categories["edges"]
        )
        has_next_page = categories["pageInfo"]["hasNextPage"]
        after = categories["pageInfo"]["endCursor"]

    return ShopifyGetAllCategoriesResponse(categories=all_subcategories)


def get_all_collections(shop: str, access_token: str) -> ShopifyGetAllCollectionsResponse:
    all_collections = []
    has_next_page = True
    after = None

    query = """
    query getCollections($after: String) {
      collections(first: 50, after: $after) {
        edges {
          cursor
          node {
            id
            title
            handle
            description
            image { src }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    while has_next_page:
        data = graphql_request(shop, access_token, query, {"after": after})
        collections = data["collections"]
        all_collections.extend(
            {
                "id": edge["node"]["id"],
                "title": edge["node"]["title"],
                "handle": edge["node"].get("handle"),
                "description": edge["node"].get("description"),
                "image": (edge["node"].get("image") or {}).get("src"),
            }
            for edge in collections["edges"]
        )
        has_next_page = collections["pageInfo"]["hasNextPage"]
        after = collections["pageInfo"]["endCursor"]

    return ShopifyGetAllCollectionsResponse.model_validate({"collections": all_collections})


def encode_shopify_credentials(shop: str, access_token: str) -> str:
    """Return JSON payload to encrypt for marketplace connection storage."""
    return json.dumps({"shop": normalize_shop(shop), "access_token": access_token})


def decode_shopify_credentials(decrypted: str) -> tuple[str, str]:
    data = json.loads(decrypted)
    if not isinstance(data, dict) or "shop" not in data or "access_token" not in data:
        raise ValueError("Invalid Shopify credentials payload")
    return normalize_shop(data["shop"]), data["access_token"]
