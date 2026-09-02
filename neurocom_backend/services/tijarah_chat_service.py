"""
Multi-marketplace conversational agent for Tijarah merchants.

Architecture: a single LangGraph tool-calling agent (langchain.agents.create_agent)
with ~16 marketplace-aware tools. Each tool is a closure bound to the merchant's
resolved credentials (TijarahContext) so the LLM never sees raw tokens.

Marketplace scoping:
  - TijarahContext carries whichever credentials were resolved at WebSocket
    connect time (Daraz only, Shopify only, or both).
  - Every tool accepts an optional `marketplace` parameter ("daraz" / "shopify").
    When omitted the tool queries ALL available marketplaces and tags each
    result row with its source marketplace.
  - The system prompt instructs the LLM to pass the marketplace explicitly
    when the merchant's query names a specific one.

Tool outputs are compact (same principle as product_chat_service.py): only
the fields a merchant needs for a chat answer, never raw API payloads. This
keeps multi-turn conversations affordable because the full message history
is resent on every LLM call.

Streaming: stream_tijarah_response yields (event, data) pairs — 'token' for
text deltas, 'tool_start'/'tool_end' for tool calls, 'visualization' for
chart specs, 'done' at end of turn, 'error' on exception.

Memory: MemorySaver per WebSocket connection — same caveat as
product_chat_service.py (single-process, not shared across workers).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import plotly.graph_objects as go
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from neurocom_backend.services.daraz_service import (
    get_all_products as daraz_get_all_products,
    get_product_by_id as daraz_get_product_by_id,
    get_all_orders_full as daraz_get_all_orders_full,
    get_order_by_id as daraz_get_order_by_id,
    get_profit_analytics,
    calculate_fee_breakdown,
    get_payout_analytics,
    get_cash_flow_analysis,
    get_returns_insights,
    get_seller_info as daraz_get_seller_info,
    scrape_product_reviews,
    get_all_products_reviews,
)
from neurocom_backend.services.shopify_service import (
    get_all_products as shopify_get_all_products,
    get_product_by_id as shopify_get_product_by_id,
    get_all_orders as shopify_get_all_orders,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context — resolved credentials for the session
# ---------------------------------------------------------------------------

@dataclass
class TijarahContext:
    daraz_access_token: Optional[str] = None
    shopify_shop: Optional[str] = None
    shopify_access_token: Optional[str] = None

    @property
    def available_marketplaces(self) -> list[str]:
        result: list[str] = []
        if self.daraz_access_token:
            result.append("daraz")
        if self.shopify_access_token:
            result.append("shopify")
        return result

    @property
    def is_single_marketplace(self) -> bool:
        return len(self.available_marketplaces) == 1

    def has_marketplace(self, name: str) -> bool:
        return name in self.available_marketplaces


def _resolve_marketplaces(
    marketplace: Optional[str], ctx: TijarahContext
) -> list[str]:
    """Return the list of marketplaces a tool should query."""
    if marketplace:
        mp = marketplace.strip().lower()
        if mp in ctx.available_marketplaces:
            return [mp]
        return ctx.available_marketplaces
    return ctx.available_marketplaces


# ---------------------------------------------------------------------------
# Tool-output formatting — keep only what's useful for a chat answer
# ---------------------------------------------------------------------------

def _format_daraz_product_compact(product) -> dict:
    prices = [sku.price for sku in product.skus if sku.price is not None]
    stock = sum(sku.Available or 0 for sku in product.skus)
    return {
        "marketplace": "daraz",
        "product_id": product.item_id,
        "title": product.attributes.name or product.attributes.name_en,
        "brand": product.attributes.brand,
        "status": product.status,
        "price_range": {"min": min(prices), "max": max(prices)} if prices else None,
        "total_stock": stock,
        "sku_count": len(product.skus),
    }


def _format_shopify_product_compact(product) -> dict:
    prices = []
    for v in product.variants:
        if v.price:
            try:
                prices.append(float(v.price))
            except (ValueError, TypeError):
                pass
    return {
        "marketplace": "shopify",
        "product_id": product.id,
        "title": product.title,
        "status": product.status,
        "product_type": product.productType,
        "price_range": {"min": min(prices), "max": max(prices)} if prices else None,
        "total_inventory": product.totalInventory,
        "variant_count": len(product.variants),
        "tags": product.tags[:5],
    }


def _format_daraz_order_compact(order: dict) -> dict:
    items = order.get("items", [])
    return {
        "marketplace": "daraz",
        "order_id": str(order.get("order_id")),
        "created_at": order.get("created_at"),
        "statuses": order.get("statuses"),
        "price": order.get("price"),
        "item_count": len(items),
        "customer": f"{order.get('customer_first_name', '')} {order.get('customer_last_name', '')}".strip() or None,
    }


def _format_shopify_order_compact(order) -> dict:
    return {
        "marketplace": "shopify",
        "order_id": order.name or order.id,
        "created_at": order.createdAt,
        "financial_status": order.displayFinancialStatus,
        "fulfillment_status": order.displayFulfillmentStatus,
        "total_amount": order.totalAmount,
        "currency": order.currencyCode,
        "item_count": len(order.lineItems),
        "customer": order.customer.displayName if order.customer else None,
    }


# ---------------------------------------------------------------------------
# Tools — closures bound to TijarahContext
# ---------------------------------------------------------------------------

def build_tijarah_tools(ctx: TijarahContext) -> list:

    # --- Catalog Tools ---

    @tool
    def get_all_products(marketplace: Optional[str] = None, limit: int = 50) -> list:
        """List products across connected marketplaces. Returns compact summary
        (title, price, stock, status) for each product. Use marketplace='daraz'
        or marketplace='shopify' to filter to one. Omit to query all."""
        results = []
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                response = daraz_get_all_products(ctx.daraz_access_token)
                for product in response.data.products[:limit]:
                    results.append(_format_daraz_product_compact(product))
            except Exception as e:
                results.append({"marketplace": "daraz", "error": str(e)})

        if "shopify" in marketplaces:
            try:
                response = shopify_get_all_products(ctx.shopify_shop, ctx.shopify_access_token)
                for product in response.products[:limit]:
                    results.append(_format_shopify_product_compact(product))
            except Exception as e:
                results.append({"marketplace": "shopify", "error": str(e)})

        return results

    @tool
    def get_product_details(product_id: str, marketplace: str = "daraz") -> dict:
        """Get full details for a specific product including variants/SKUs.
        Requires marketplace='daraz' or marketplace='shopify'.
        For Daraz, product_id is the numeric item_id.
        For Shopify, product_id is the GraphQL product GID."""
        if marketplace == "daraz" and ctx.has_marketplace("daraz"):
            try:
                response = daraz_get_product_by_id(int(product_id), ctx.daraz_access_token)
                product = response.data
                prices = [sku.price for sku in product.skus if sku.price is not None]
                stock = sum(sku.Available or 0 for sku in product.skus)
                return {
                    "marketplace": "daraz",
                    "product_id": product.item_id,
                    "title": product.attributes.name or product.attributes.name_en,
                    "brand": product.attributes.brand,
                    "status": product.status,
                    "category": product.primary_category_name,
                    "description": (product.attributes.description or "")[:500],
                    "price_range": {"min": min(prices), "max": max(prices)} if prices else None,
                    "total_stock": stock,
                    "skus": [
                        {
                            "sku_id": sku.SkuId,
                            "seller_sku": sku.SellerSku,
                            "price": sku.price,
                            "stock": sku.Available,
                            "status": sku.Status,
                        }
                        for sku in product.skus
                    ],
                }
            except Exception as e:
                return {"error": f"Could not fetch Daraz product: {e}"}

        elif marketplace == "shopify" and ctx.has_marketplace("shopify"):
            try:
                response = shopify_get_product_by_id(ctx.shopify_shop, ctx.shopify_access_token, product_id)
                if not response.product:
                    return {"error": "Product not found on Shopify"}
                p = response.product
                return {
                    "marketplace": "shopify",
                    "product_id": p.id,
                    "title": p.title,
                    "handle": p.handle,
                    "status": p.status,
                    "product_type": p.productType,
                    "description": (p.description or "")[:500],
                    "tags": p.tags,
                    "total_inventory": p.totalInventory,
                    "variants": [
                        {
                            "id": v.id,
                            "title": v.title,
                            "price": v.price,
                            "inventory": v.inventoryQuantity,
                        }
                        for v in p.variants
                    ],
                }
            except Exception as e:
                return {"error": f"Could not fetch Shopify product: {e}"}

        return {"error": f"Marketplace '{marketplace}' is not connected or invalid product_id"}

    @tool
    def search_products(query: str, marketplace: Optional[str] = None) -> list:
        """Search products by name/title across connected marketplaces.
        Returns matching products with compact summary. Pass marketplace to
        restrict to one marketplace."""
        query_lower = query.lower()
        results = []
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                response = daraz_get_all_products(ctx.daraz_access_token)
                for product in response.data.products:
                    title = (product.attributes.name or product.attributes.name_en or "").lower()
                    if query_lower in title:
                        results.append(_format_daraz_product_compact(product))
            except Exception as e:
                results.append({"marketplace": "daraz", "error": str(e)})

        if "shopify" in marketplaces:
            try:
                response = shopify_get_all_products(ctx.shopify_shop, ctx.shopify_access_token)
                for product in response.products:
                    if query_lower in (product.title or "").lower():
                        results.append(_format_shopify_product_compact(product))
            except Exception as e:
                results.append({"marketplace": "shopify", "error": str(e)})

        return results

    # --- Order Tools ---

    @tool
    def get_orders(
        marketplace: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 30,
    ) -> list:
        """List recent orders across connected marketplaces. Returns compact
        summary (order_id, date, status, total, customer). Use marketplace to
        filter. Supports date range filtering with start_date/end_date (YYYY-MM-DD)."""
        results = []
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                response = daraz_get_all_orders_full(
                    ctx.daraz_access_token, start_date=start_date, end_date=end_date
                )
                for order in response.get("orders", [])[:limit]:
                    results.append(_format_daraz_order_compact(order))
            except Exception as e:
                results.append({"marketplace": "daraz", "error": str(e)})

        if "shopify" in marketplaces:
            try:
                response = shopify_get_all_orders(ctx.shopify_shop, ctx.shopify_access_token)
                for order in response.orders[:limit]:
                    results.append(_format_shopify_order_compact(order))
            except Exception as e:
                results.append({"marketplace": "shopify", "error": str(e)})

        return results

    @tool
    def get_order_details(order_id: str, marketplace: str = "daraz") -> dict:
        """Get full details for a specific order including line items, customer
        info, and shipping details. Requires marketplace parameter."""
        if marketplace == "daraz" and ctx.has_marketplace("daraz"):
            try:
                order = daraz_get_order_by_id(order_id, ctx.daraz_access_token)
                return {
                    "marketplace": "daraz",
                    "order_id": str(order.get("order_id")),
                    "created_at": order.get("created_at"),
                    "updated_at": order.get("updated_at"),
                    "statuses": order.get("statuses"),
                    "price": order.get("price"),
                    "payment_method": order.get("payment_method"),
                    "customer": {
                        "first_name": order.get("customer_first_name"),
                        "last_name": order.get("customer_last_name"),
                    },
                    "items": [
                        {
                            "name": item.get("name"),
                            "sku_id": item.get("sku_id"),
                            "status": item.get("status"),
                            "item_price": item.get("item_price"),
                            "paid_price": item.get("paid_price"),
                            "quantity": item.get("quantity"),
                        }
                        for item in order.get("items", [])
                    ],
                }
            except Exception as e:
                return {"error": f"Could not fetch Daraz order: {e}"}

        elif marketplace == "shopify" and ctx.has_marketplace("shopify"):
            try:
                response = shopify_get_all_orders(ctx.shopify_shop, ctx.shopify_access_token)
                for order in response.orders:
                    if order.name == order_id or order.id == order_id:
                        return {
                            "marketplace": "shopify",
                            "order_id": order.name,
                            "created_at": order.createdAt,
                            "financial_status": order.displayFinancialStatus,
                            "fulfillment_status": order.displayFulfillmentStatus,
                            "total_amount": order.totalAmount,
                            "currency": order.currencyCode,
                            "customer": {
                                "name": order.customer.displayName if order.customer else None,
                                "email": order.customer.email if order.customer else None,
                            },
                            "items": [
                                {
                                    "title": li.title,
                                    "quantity": li.quantity,
                                    "price": li.price,
                                    "variant": li.variant.title if li.variant else None,
                                }
                                for li in order.lineItems
                            ],
                        }
                return {"error": f"Shopify order {order_id} not found"}
            except Exception as e:
                return {"error": f"Could not fetch Shopify order: {e}"}

        return {"error": f"Marketplace '{marketplace}' is not connected"}

    # --- Review Tools ---

    @tool
    def get_product_reviews(product_url_or_id: str, marketplace: str = "daraz") -> dict:
        """Get customer reviews and ratings for a specific product.
        For Daraz: pass the product URL (e.g. https://www.daraz.pk/products/...-i12345.html)
        or just the item_id as string.
        For Shopify: pass the product GID.
        Returns average rating, total reviews, and individual review content."""
        if marketplace == "daraz" and ctx.has_marketplace("daraz"):
            try:
                if product_url_or_id.startswith("http"):
                    product_url = product_url_or_id
                else:
                    product_url = f"https://www.daraz.pk/products/-i{product_url_or_id}.html"
                scraped = scrape_product_reviews(product_url)
                return {
                    "marketplace": "daraz",
                    "average_rating": scraped.average_rating,
                    "total_reviews": scraped.total_reviews,
                    "reviews": [
                        {
                            "rating": r.rating,
                            "content": r.content,
                            "date": r.review_date,
                        }
                        for r in scraped.reviews[:20]
                    ],
                }
            except Exception as e:
                return {"error": f"Could not fetch Daraz reviews: {e}"}

        elif marketplace == "shopify" and ctx.has_marketplace("shopify"):
            return {"message": "Shopify does not expose product reviews via the Admin API. Use Daraz for review data."}

        return {"error": f"Marketplace '{marketplace}' is not connected"}

    @tool
    def get_reviews_summary(marketplace: Optional[str] = None) -> dict:
        """Get store-wide review statistics: average ratings across products,
        product ranking by review count and rating. Currently only supported
        for Daraz."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                reviews_data = get_all_products_reviews(ctx.daraz_access_token)
                if isinstance(reviews_data, dict):
                    results["daraz"] = {
                        "total_products_with_reviews": len(reviews_data.get("data", [])),
                        "summary": "Use get_product_reviews for individual product review details.",
                    }
                else:
                    results["daraz"] = {"raw_count": len(reviews_data) if reviews_data else 0}
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            results["shopify"] = {"message": "Shopify Admin API does not expose product reviews."}

        return results

    # --- Financial Tools ---

    @tool
    def get_financial_summary(
        marketplace: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Get revenue, costs, net profit, and profit margin for the given period.
        For Daraz: uses transaction-level data from the Finance API.
        For Shopify: calculates from order totals.
        Returns: total_revenue, total_costs, net_profit, profit_margin, order_count."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                profit = get_profit_analytics(ctx.daraz_access_token, start_date, end_date)
                results["daraz"] = {
                    "total_revenue": profit["total_revenue"],
                    "total_costs": profit["total_costs"],
                    "net_profit": profit["net_profit"],
                    "profit_margin": profit["profit_margin"],
                    "order_count": profit["order_count"],
                    "currency": "PKR",
                }
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            try:
                orders_response = shopify_get_all_orders(ctx.shopify_shop, ctx.shopify_access_token)
                total_revenue = 0.0
                order_count = 0
                for order in orders_response.orders:
                    if order.totalAmount:
                        try:
                            total_revenue += float(order.totalAmount)
                            order_count += 1
                        except (ValueError, TypeError):
                            pass
                results["shopify"] = {
                    "total_revenue": round(total_revenue, 2),
                    "order_count": order_count,
                    "currency": orders_response.orders[0].currencyCode if orders_response.orders else "USD",
                    "note": "Shopify revenue is calculated from order totals. Cost breakdown not available via Admin API.",
                }
            except Exception as e:
                results["shopify"] = {"error": str(e)}

        return results

    @tool
    def get_fee_breakdown(
        marketplace: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Get detailed fee breakdown: commission, payment fees, shipping fees,
        penalties, promotional discounts. Currently only supported for Daraz
        (which provides transaction-level fee data)."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                breakdown = calculate_fee_breakdown(ctx.daraz_access_token, start_date, end_date)
                results["daraz"] = breakdown
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            results["shopify"] = {
                "message": "Shopify does not provide fee breakdown via Admin API. Check your Shopify Payments dashboard."
            }

        return results

    @tool
    def get_payout_info(
        marketplace: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Get payout status and amounts: total payouts, paid vs upcoming,
        amounts per payout. Currently only supported for Daraz."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                analytics = get_payout_analytics(ctx.daraz_access_token, start_date, end_date)
                results["daraz"] = {
                    "total_payouts": analytics["total_payouts"],
                    "total_amount": analytics["total_amount"],
                    "paid_amount": analytics["paid_amount"],
                    "upcoming_amount": analytics["upcoming_amount"],
                    "recent_paid": [
                        {
                            "payout_id": p["payout_id"],
                            "amount": p["amount"],
                            "created_at": p["created_at"],
                        }
                        for p in analytics.get("paid", [])[:5]
                    ],
                    "currency": "PKR",
                }
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            results["shopify"] = {"message": "Shopify payouts are managed via Shopify Payments dashboard."}

        return results

    @tool
    def get_cash_flow(marketplace: Optional[str] = None, days: int = 30) -> dict:
        """Get daily cash flow (inflow vs outflow) for the past N days.
        For Daraz: transaction-level daily breakdown.
        For Shopify: daily order totals."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                flow = get_cash_flow_analysis(ctx.daraz_access_token, days)
                results["daraz"] = {
                    "period_days": days,
                    "daily_flow": flow[-14:],  # last 14 days for compactness
                    "currency": "PKR",
                }
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            try:
                orders_response = shopify_get_all_orders(ctx.shopify_shop, ctx.shopify_access_token)
                daily: dict = {}
                cutoff = datetime.now() - timedelta(days=days)
                for order in orders_response.orders:
                    if order.createdAt and order.totalAmount:
                        try:
                            order_date = datetime.fromisoformat(order.createdAt.replace("Z", "+00:00"))
                            if order_date >= cutoff:
                                day_key = order_date.strftime("%Y-%m-%d")
                                daily[day_key] = daily.get(day_key, 0.0) + float(order.totalAmount)
                        except (ValueError, TypeError):
                            pass
                results["shopify"] = {
                    "period_days": days,
                    "daily_inflow": [{"date": k, "inflow": round(v, 2)} for k, v in sorted(daily.items())[-14:]],
                    "currency": orders_response.orders[0].currencyCode if orders_response.orders else "USD",
                }
            except Exception as e:
                results["shopify"] = {"error": str(e)}

        return results

    # --- Returns / Operations Tools ---

    @tool
    def get_returns_analysis(
        marketplace: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """Get return/refund analysis: return rate, top return reasons, refund
        amounts, dispute rates. Currently only supported for Daraz."""
        results = {}
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                insights = get_returns_insights(ctx.daraz_access_token, start_date=start_date, end_date=end_date)
                results["daraz"] = {
                    "total_units_sold": insights.get("total_units_sold"),
                    "total_units_returned": insights.get("total_units_returned"),
                    "overall_return_rate": insights.get("overall_return_rate"),
                    "total_refund_amount": insights.get("total_refund_amount"),
                    "dispute_rate": insights.get("dispute_rate"),
                    "top_reasons": insights.get("return_reason_breakdown", [])[:5],
                    "recommendations": insights.get("recommendations", []),
                }
            except Exception as e:
                results["daraz"] = {"error": str(e)}

        if "shopify" in marketplaces:
            results["shopify"] = {
                "message": "Shopify return analysis requires Shopify Admin API order refund data. Check your Shopify admin."
            }

        return results

    @tool
    def get_top_products(metric: str = "orders", marketplace: Optional[str] = None, limit: int = 10) -> list:
        """Rank products by a performance metric. Supported metrics:
        - 'orders': most ordered products
        - 'rating': highest rated products
        - 'stock': highest stock levels
        Returns top N products with their metric value."""
        results = []
        marketplaces = _resolve_marketplaces(marketplace, ctx)

        if "daraz" in marketplaces:
            try:
                products_response = daraz_get_all_products(ctx.daraz_access_token)
                products = products_response.data.products

                if metric == "stock":
                    for p in products:
                        stock = sum(sku.Available or 0 for sku in p.skus)
                        results.append({
                            "marketplace": "daraz",
                            "product_id": p.item_id,
                            "title": p.attributes.name or p.attributes.name_en,
                            "metric_value": stock,
                            "metric": "stock",
                        })
                elif metric == "rating":
                    # For rating we'd need per-product review scraping which is slow.
                    # Return products with a note to use get_product_reviews for details.
                    results.append({
                        "marketplace": "daraz",
                        "message": "Use get_product_reviews for individual product ratings. Bulk rating data requires per-product scraping.",
                    })
                else:
                    # Default: by orders — fetch orders and count product frequency
                    orders_res = daraz_get_all_orders_full(ctx.daraz_access_token)
                    product_order_count: dict = {}
                    for order in orders_res.get("orders", []):
                        for item in order.get("items", []):
                            name = item.get("name", "Unknown")
                            product_order_count[name] = product_order_count.get(name, 0) + 1

                    sorted_products = sorted(product_order_count.items(), key=lambda x: x[1], reverse=True)[:limit]
                    for name, count in sorted_products:
                        results.append({
                            "marketplace": "daraz",
                            "title": name,
                            "metric_value": count,
                            "metric": "orders",
                        })
                    return results

                results.sort(key=lambda x: x.get("metric_value", 0), reverse=True)
                return results[:limit]
            except Exception as e:
                return [{"marketplace": "daraz", "error": str(e)}]

        if "shopify" in marketplaces:
            try:
                products_response = shopify_get_all_products(ctx.shopify_shop, ctx.shopify_access_token)
                products = products_response.products

                if metric == "stock":
                    for p in products:
                        results.append({
                            "marketplace": "shopify",
                            "product_id": p.id,
                            "title": p.title,
                            "metric_value": p.totalInventory or 0,
                            "metric": "stock",
                        })
                else:
                    orders_response = shopify_get_all_orders(ctx.shopify_shop, ctx.shopify_access_token)
                    product_order_count: dict = {}
                    for order in orders_response.orders:
                        for li in order.lineItems:
                            product_order_count[li.title] = product_order_count.get(li.title, 0) + li.quantity

                    sorted_products = sorted(product_order_count.items(), key=lambda x: x[1], reverse=True)[:limit]
                    for name, count in sorted_products:
                        results.append({
                            "marketplace": "shopify",
                            "title": name,
                            "metric_value": count,
                            "metric": "orders",
                        })
                    return results

                results.sort(key=lambda x: x.get("metric_value", 0), reverse=True)
                return results[:limit]
            except Exception as e:
                return [{"marketplace": "shopify", "error": str(e)}]

        return results

    # --- Seller Info ---

    @tool
    def get_seller_info(marketplace: str = "daraz") -> dict:
        """Get seller profile and store information. Currently only supported
        for Daraz."""
        if marketplace == "daraz" and ctx.has_marketplace("daraz"):
            try:
                info = daraz_get_seller_info(ctx.daraz_access_token)
                seller_data = info.get("data", {})
                return {
                    "marketplace": "daraz",
                    "seller_id": seller_data.get("seller_id"),
                    "seller_name": seller_data.get("name"),
                    "email": seller_data.get("email"),
                    "phone": seller_data.get("phone"),
                    "address": seller_data.get("seller_address"),
                    "verified": seller_data.get("is_verified"),
                }
            except Exception as e:
                return {"error": f"Could not fetch Daraz seller info: {e}"}

        elif marketplace == "shopify" and ctx.has_marketplace("shopify"):
            return {"message": "Shopify seller info is available via the shop GraphQL query. Use get_all_products to verify store access."}

        return {"error": f"Marketplace '{marketplace}' is not connected"}

    # --- Visualization Tool ---

    @tool
    def create_visualization(
        chart_type: str,
        data: str,
        title: str = "Chart",
        x_label: str = "",
        y_label: str = "",
    ) -> dict:
        """Generate a Plotly chart specification as JSON for frontend rendering.
        The agent should call this AFTER gathering data with other tools.

        Parameters:
        - chart_type: 'bar', 'line', 'pie', 'scatter', 'area'
        - data: JSON string with the data to visualize. Expected formats:
          For bar/line/scatter/area: {"labels": [...], "values": [...]} or
          {"labels": [...], "series": [{"name": "s1", "values": [...]}, ...]}
          For pie: {"labels": [...], "values": [...]}
        - title: chart title
        - x_label: x-axis label
        - y_label: y-axis label

        Returns a Plotly-compatible JSON spec that the frontend renders."""
        try:
            parsed_data = json.loads(data) if isinstance(data, str) else data
        except json.JSONDecodeError:
            return {"error": "Invalid JSON data for visualization"}

        try:
            fig = go.Figure()
            labels = parsed_data.get("labels", [])
            values = parsed_data.get("values", [])
            series_list = parsed_data.get("series", [])

            if chart_type == "pie":
                fig.add_trace(go.Pie(labels=labels, values=values, textinfo="label+percent"))
                fig.update_layout(title=title)

            elif chart_type == "bar":
                if series_list:
                    for s in series_list:
                        fig.add_trace(go.Bar(name=s["name"], x=labels, y=s["values"]))
                else:
                    fig.add_trace(go.Bar(x=labels, y=values, name=title))
                fig.update_layout(title=title, xaxis_title=x_label, yaxis_title=y_label, barmode="group")

            elif chart_type == "line":
                if series_list:
                    for s in series_list:
                        fig.add_trace(go.Scatter(name=s["name"], x=labels, y=s["values"], mode="lines+markers"))
                else:
                    fig.add_trace(go.Scatter(x=labels, y=values, mode="lines+markers", name=title))
                fig.update_layout(title=title, xaxis_title=x_label, yaxis_title=y_label)

            elif chart_type == "area":
                if series_list:
                    for s in series_list:
                        fig.add_trace(go.Scatter(name=s["name"], x=labels, y=s["values"], fill="tozeroy", mode="lines"))
                else:
                    fig.add_trace(go.Scatter(x=labels, y=values, fill="tozeroy", mode="lines", name=title))
                fig.update_layout(title=title, xaxis_title=x_label, yaxis_title=y_label)

            elif chart_type == "scatter":
                fig.add_trace(go.Scatter(x=labels, y=values, mode="markers", name=title))
                fig.update_layout(title=title, xaxis_title=x_label, yaxis_title=y_label)

            else:
                return {"error": f"Unsupported chart_type: {chart_type}. Use bar, line, pie, scatter, or area."}

            fig.update_layout(template="plotly_white", height=400)
            plotly_spec = fig.to_dict()

            return {
                "chart_type": chart_type,
                "title": title,
                "plotly_spec": plotly_spec,
            }
        except Exception as e:
            return {"error": f"Could not create visualization: {e}"}

    # Collect all tools
    return [
        get_all_products,
        get_product_details,
        search_products,
        get_orders,
        get_order_details,
        get_product_reviews,
        get_reviews_summary,
        get_financial_summary,
        get_fee_breakdown,
        get_payout_info,
        get_cash_flow,
        get_returns_analysis,
        get_top_products,
        get_seller_info,
        create_visualization,
    ]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(ctx: TijarahContext) -> str:
    marketplaces = ", ".join(ctx.available_marketplaces) if ctx.available_marketplaces else "none"
    single_note = ""
    if ctx.is_single_marketplace and ctx.available_marketplaces:
        single_note = (
            f"\n\nIMPORTANT: Only {ctx.available_marketplaces[0].upper()} is connected for this session. "
            f"All queries should be answered using {ctx.available_marketplaces[0].upper()} data only. "
            f"If the user asks about the other marketplace, inform them it is not connected."
        )

    return f"""You are Tijarah, an AI business assistant for multi-marketplace merchants selling on Daraz and Shopify.
You help merchants understand their products, orders, reviews, financials, and operations across their connected stores.

CONNECTED MARKETPLACES: {marketplaces}{single_note}

RULES:
1. When the merchant mentions a specific marketplace (Daraz/Shopify) in their query,
   pass marketplace="daraz" or marketplace="shopify" to EVERY tool call.
2. When no marketplace is mentioned, query ALL available marketplaces and present
   results side-by-side with marketplace labels.
3. Always cite concrete numbers from tools. Never guess financial figures.
4. For "top products" queries, use get_top_products with the appropriate metric
   (orders, stock, rating).
5. For revenue/profit queries, use get_financial_summary with appropriate date ranges.
   Use start_date and end_date in YYYY-MM-DD format.
6. For visualization requests, first gather the data using other tools, then call
   create_visualization with the data formatted as JSON.
7. Keep answers concise. Use tables for comparisons across marketplaces.
8. When comparing marketplaces, always label which data comes from which marketplace.
9. For returns/refund analysis, use get_returns_analysis (Daraz only).
10. For fee breakdowns, use get_fee_breakdown (Daraz only).
11. If a tool returns an error, inform the merchant and suggest alternatives.
12. Today's date is {datetime.now().strftime('%Y-%m-%d')}. Use this for relative date queries
    like "last quarter", "this month", etc."""


# ---------------------------------------------------------------------------
# Agent builder
# ---------------------------------------------------------------------------

def build_tijarah_agent(context: TijarahContext):
    """Build a LangGraph agent with all Tijarah tools bound to the context."""
    tools = build_tijarah_tools(context)
    llm = ChatOpenAI(
        temperature=0,
        model="gpt-5.6-luna",
        streaming=True,
        reasoning_effort="none",
    )
    system_prompt = _build_system_prompt(context)
    return create_agent(llm, tools, system_prompt=system_prompt, checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Streaming pipeline
# ---------------------------------------------------------------------------

async def stream_tijarah_response(agent, thread_id: str, user_message: str):
    """Yields (event, data) pairs: 'tool_start'/'tool_end' as the agent calls
    tools, 'token' for each streamed text delta, 'visualization' for chart
    specs, 'done' at the end of the turn. A mid-turn exception becomes a
    final 'error' event instead of crashing the connection."""
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
                    # Check if the content contains a visualization spec
                    yield "token", {"content": content}
            elif kind == "on_tool_start":
                yield "tool_start", {"name": event.get("name"), "input": event["data"].get("input")}
            elif kind == "on_tool_end":
                output = event["data"].get("output")
                output_content = getattr(output, "content", output)

                # Check if tool output contains a visualization spec
                if event.get("name") == "create_visualization":
                    try:
                        if isinstance(output_content, str):
                            viz_data = json.loads(output_content)
                        elif isinstance(output_content, dict):
                            viz_data = output_content
                        else:
                            viz_data = {"raw": str(output_content)}

                        if isinstance(viz_data, dict) and "plotly_spec" in viz_data:
                            yield "visualization", {
                                "chart_type": viz_data.get("chart_type"),
                                "title": viz_data.get("title"),
                                "plotly_spec": viz_data.get("plotly_spec"),
                            }
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

                yield "tool_end", {"name": event.get("name"), "output": output_content}
        yield "done", {}
    except Exception as exc:
        yield "error", {"detail": str(exc)}
