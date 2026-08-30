"""Daraz catalog scraper — fetches products by category/keyword from the
public /catalog/?ajax=true endpoint. No Daraz API key or seller auth needed.

Uses plain HTTP requests with browser-like headers. Optionally accepts
session cookies for higher rate limits.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlencode

import requests

logger = logging.getLogger(__name__)

_CATALOG_BASE = "https://www.daraz.pk/catalog/"

_DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.8",
    "cache-control": "no-cache",
    "referer": "https://www.daraz.pk/",
    "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Brave";v="152"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
}

_PAGE_SIZE = 40
_REQUEST_DELAY_SECONDS = 1.5


def _build_catalog_url(
    query: str,
    page: int = 1,
    sort_by: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    service: str = "all_channel",
    extra_params: Optional[Dict[str, str]] = None,
) -> str:
    params: Dict[str, Any] = {
        "ajax": "true",
        "from": "hp_categories",
        "page": str(page),
        "q": query,
        "service": service,
        "src": "all_channel",
    }
    if sort_by:
        params["sort"] = sort_by
    if price_min is not None:
        params["price"] = f"{price_min}-{price_max}" if price_max else f"{price_min}-"
    if extra_params:
        params.update(extra_params)
    return f"{_CATALOG_BASE}?{urlencode(params)}"


def _parse_total_pages(filters_data: dict) -> int:
    filtered_qty = filters_data.get("filteredQuatity", "0")
    try:
        total = int(str(filtered_qty).replace(",", ""))
    except (ValueError, TypeError):
        total = 0
    if total <= 0:
        return 1
    return max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)


def _extract_subcategories(filters_data: dict) -> list:
    for f in filters_data.get("filterItems", []):
        if f.get("uniqueName") == "category":
            return [
                {"title": opt.get("title", ""), "value": opt.get("value", ""), "url": opt.get("url", "")}
                for opt in f.get("options", [])
            ]
    return []


def _extract_filters(filters_data: dict) -> list:
    filters = []
    for f in filters_data.get("filterItems", []):
        if f.get("uniqueName") == "category":
            continue
        options = [
            {"title": opt.get("title", ""), "value": opt.get("value", "")}
            for opt in f.get("options", [])
            if opt.get("title")
        ]
        if options:
            filters.append({
                "name": f.get("name", ""),
                "title": f.get("title", ""),
                "type": f.get("type", ""),
                "options": options,
            })
    return filters


def fetch_catalog_products(
    query: str,
    page: int = 1,
    sort_by: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    cookies: Optional[Dict[str, str]] = None,
    extra_params: Optional[Dict[str, str]] = None,
) -> dict:
    url = _build_catalog_url(query, page, sort_by, price_min, price_max, extra_params=extra_params)
    headers = {**_DEFAULT_HEADERS}
    session = requests.Session()
    if cookies:
        session.cookies.update(cookies)

    logger.info("catalog_scraper: fetching page=%d query=%s", page, query)
    resp = session.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def scrape_products_by_category(
    query: str,
    page: int = 1,
    max_pages: int = 1,
    sort_by: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    cookies: Optional[Dict[str, str]] = None,
) -> dict:
    all_products = []
    filters_data = {}
    total_pages = 1

    pages_to_fetch = min(max_pages, 50)

    for current_page in range(page, page + pages_to_fetch):
        data = fetch_catalog_products(
            query=query,
            page=current_page,
            sort_by=sort_by,
            price_min=price_min,
            price_max=price_max,
            cookies=cookies,
        )

        mods = data.get("mods", {})
        filter_mod = mods.get("filter", {})
        list_items = mods.get("listItems", [])

        if current_page == page:
            filters_data = filter_mod
            total_pages = _parse_total_pages(filter_mod)

        for item in list_items:
            if item.get("tItemType") == "nt_product":
                all_products.append(item)

        if not list_items or current_page >= total_pages:
            break

        if current_page < page + pages_to_fetch - 1:
            time.sleep(_REQUEST_DELAY_SECONDS)

    subcategories = _extract_subcategories(filters_data)
    available_filters = _extract_filters(filters_data)

    return {
        "query": query,
        "page": page,
        "total_pages": total_pages,
        "total_products": len(all_products),
        "products": all_products,
        "available_filters": available_filters,
        "subcategories": subcategories,
    }


def hunt_products_for_niche(
    niche: str,
    max_pages: int = 3,
    min_rating: float = 0,
    min_reviews: int = 0,
    max_price: Optional[int] = None,
    cookies: Optional[Dict[str, str]] = None,
) -> dict:
    raw = scrape_products_by_category(
        query=niche,
        page=1,
        max_pages=max_pages,
        cookies=cookies,
    )

    filtered = []
    for p in raw["products"]:
        try:
            rating = float(p.get("ratingScore", 0) or 0)
        except (ValueError, TypeError):
            rating = 0
        try:
            reviews = int(p.get("review", 0) or 0)
        except (ValueError, TypeError):
            reviews = 0
        try:
            price = int(p.get("price", 0) or 0)
        except (ValueError, TypeError):
            price = 0

        if rating < min_rating:
            continue
        if reviews < min_reviews:
            continue
        if max_price and price > max_price:
            continue

        filtered.append(p)

    filtered.sort(key=lambda p: (float(p.get("ratingScore", 0) or 0), int(p.get("review", 0) or 0)), reverse=True)

    return {
        "niche": niche,
        "total_scraped": raw["total_products"],
        "total_recommended": len(filtered),
        "subcategories": raw.get("subcategories", []),
        "recommended_products": filtered,
    }
