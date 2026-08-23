import re
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional, Dict, Any

class Sku(BaseModel):
    SellerSku: str
    Url: str
    color_family: str
    size: str
    quantity: int
    price: float
    package_length: int
    package_height: int
    package_weight: int
    package_width: int
    package_content: str
    Images: List[str]

class DarazProductCreate(BaseModel):
    PrimaryCategory: int
    name: str
    short_description: str
    # short_description_en: Optional[str]
    description: str
    # description_en: Optional[str]
    brand: str
    model: str
    kid_years: str
    name_en: str
    occasion: str
    age_range: str
    warranty_type: str
    Images: List[str]
    Skus: List[Sku]


# ---------------------------------------------------------------------------
# Shapes returned by GET /products/get (daraz_service.get_all_products)
# ---------------------------------------------------------------------------

_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "article", "tr")


def _html_to_text(value: Optional[str]) -> Optional[str]:
    """Strip Daraz's rich-text HTML (description/description_en/...) down to
    plain, readable text so API consumers don't get raw markup.

    Inline tags (span, b, a, ...) are joined with spaces so a sentence split
    across several styled spans doesn't get broken onto separate lines;
    block tags (p, div, li, ...) get a line break so paragraph/list
    structure is preserved.
    """
    if not value:
        return value
    if "<" not in value:
        # Already plain text — e.g. we're re-validating a payload that was
        # already cleaned once and cached. BeautifulSoup's per-call parser
        # setup has real fixed overhead even when there's no markup to
        # parse, and this runs on every product/every field on every cache
        # read, so skipping it here matters for cache-hit latency.
        return value.strip()
    soup = BeautifulSoup(value, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(_BLOCK_TAGS):
        block.append("\n")
    text = soup.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class DarazSkuWarehouseInventory(BaseModel):
    occupyQuantity: int
    quantity: int
    totalQuantity: int
    bizType: int
    withholdQuantity: int
    bizCode: str
    warehouseType: str
    warehouseCode: str
    sellableQuantity: int


class DarazProductSku(BaseModel):
    # saleProp keys (color_family, size, ...) are sometimes duplicated as
    # top-level sku fields and vary per product, so extras are kept.
    model_config = ConfigDict(extra="allow")

    SkuId: int
    SellerSku: str
    ShopSku: str
    Status: str
    quantity: int
    Available: int
    Images: List[str] = []
    Url: Optional[str] = None
    price: float
    special_price: Optional[float] = None
    special_from_date: Optional[str] = None
    special_to_date: Optional[str] = None
    special_from_time: Optional[str] = None
    special_to_time: Optional[str] = None
    special_time_format: Optional[str] = None
    package_length: Optional[str] = None
    package_width: Optional[str] = None
    package_height: Optional[str] = None
    package_weight: Optional[str] = None
    saleProp: Dict[str, str] = {}
    multiWarehouseInventories: List[DarazSkuWarehouseInventory] = []
    fblWarehouseInventories: List[Any] = []
    channelInventories: List[Any] = []


class DarazProductAttributes(BaseModel):
    # Attribute keys are category-specific (e.g. usage, occasion, material,
    # cutlery_type, drying_rack_materials, ...), so extras are kept.
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    description_en: Optional[str] = None
    short_description: Optional[str] = None
    short_description_en: Optional[str] = None
    brand: Optional[str] = None
    warranty_type: Optional[str] = None
    Hazmat: Optional[str] = None
    video: Optional[str] = None
    source: Optional[str] = None
    delivery_option_standard: Optional[str] = None
    delivery_option_sof: Optional[str] = None
    express_delivery: Optional[str] = None
    promotion_whitebkg_image: List[str] = []

    @field_validator(
        "description", "description_en", "short_description", "short_description_en",
        mode="before",
    )
    @classmethod
    def _clean_html_fields(cls, value: Optional[str]) -> Optional[str]:
        return _html_to_text(value)


class DarazProduct(BaseModel):
    item_id: int
    primary_category: int
    status: str
    created_time: str
    updated_time: str
    images: List[str] = []
    skus: List[DarazProductSku] = []
    attributes: DarazProductAttributes


class DarazProductsData(BaseModel):
    total_products: int
    products: List[DarazProduct]


class DarazGetAllProductsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: DarazProductsData
    code: str
    request_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Shapes returned by GET /order/reverse/return/detail/list
# (daraz_service.get_all_reverse_orders_info)
# ---------------------------------------------------------------------------

class ReverseOrderLineProduct(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: int
    sku: str


class ReverseOrderBuyer(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: int


class ReverseOrderLine(BaseModel):
    model_config = ConfigDict(extra="allow")

    reverse_order_line_id: int
    trade_order_line_id: int
    platform_sku_id: str
    seller_sku_id: str
    productDTO: ReverseOrderLineProduct
    buyer: ReverseOrderBuyer
    reason_code: int
    reason_text: str
    reverse_status: str
    ofc_status: str
    whqc_decision: Optional[str] = None
    is_need_refund: bool
    is_dispute: bool
    item_unit_price: int
    refund_amount: int
    refund_payment_method: str
    tracking_number: str
    trade_order_gmt_create: int
    return_order_line_gmt_create: int
    return_order_line_gmt_modified: int


class ReverseOrderData(BaseModel):
    model_config = ConfigDict(extra="allow")

    reverse_order_id: int
    trade_order_id: int
    request_type: str
    shipping_type: str
    is_rtm: bool
    reverseOrderLineDTOList: List[ReverseOrderLine] = []


class ReverseOrderInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    data: ReverseOrderData
    code: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = Field(default=None, alias="_trace_id_")


# ---------------------------------------------------------------------------
# Shapes returned by the public Daraz PDP review widget API
# (GET https://my.daraz.pk/pdp/review/getReviewList), used by
# daraz_service.scrape_product_reviews to get a product's full review
# history from its storefront URL. The seller API (get_product_reviews)
# only exposes a rolling 7-day window; this endpoint has no such limit.
# ---------------------------------------------------------------------------

class ScrapedProductReview(BaseModel):
    review_id: int = Field(alias="reviewRateId")
    buyer_name: Optional[str] = Field(default=None, alias="buyerName")
    rating: int
    content: Optional[str] = Field(default=None, alias="reviewContent")
    review_date: Optional[str] = Field(default=None, alias="reviewTime")
    bought_date: Optional[str] = Field(default=None, alias="boughtDate")
    like_count: int = Field(default=0, alias="likeCount")
    images: List[str] = []

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("images", mode="before")
    @classmethod
    def _extract_image_urls(cls, value: Any) -> List[str]:
        if not value:
            return []
        return [img.get("url") for img in value if isinstance(img, dict) and img.get("url")]


class ScrapedProductReviewsResponse(BaseModel):
    item_id: str
    total_reviews: int
    average_rating: Optional[float] = None
    reviews: List[ScrapedProductReview]


# ---------------------------------------------------------------------------
# Shapes returned by daraz_service.get_orders_with_items — orders from
# /orders/get merged with their line items from /orders/items/get. Both
# endpoints return many more fields than are modeled here (voucher/fee
# breakdowns, shipping metadata, ...), so extras are kept rather than
# validated field-by-field.
# ---------------------------------------------------------------------------

class OrderAddress(BaseModel):
    model_config = ConfigDict(extra="allow")

    country: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    address3: Optional[str] = None
    address4: Optional[str] = None
    address5: Optional[str] = None
    post_code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    order_item_id: int
    order_id: int
    sku: Optional[str] = None
    sku_id: Optional[str] = None
    shop_sku: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    item_price: Optional[float] = None
    paid_price: Optional[float] = None
    currency: Optional[str] = None
    product_main_image: Optional[str] = None
    tracking_code: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OrderWithItems(BaseModel):
    model_config = ConfigDict(extra="allow")

    order_id: int
    order_number: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    price: Optional[str] = None
    payment_method: Optional[str] = None
    items_count: Optional[int] = None
    statuses: List[str] = []
    address_billing: Optional[OrderAddress] = None
    address_shipping: Optional[OrderAddress] = None
    items: List[OrderItem] = []


class OrdersWithItemsResponse(BaseModel):
    orders: List[OrderWithItems]
    count: int


# ---------------------------------------------------------------------------
# daraz_service.get_returns_insights — return-rate / complaint-pattern
# analytics built by joining get_orders_with_items (units sold) against
# get_all_reverse_orders_info (units returned).
# ---------------------------------------------------------------------------

class ReturnReasonBreakdown(BaseModel):
    reason: str
    count: int
    percentage: float
    likely_cause: str


class ProductReturnStats(BaseModel):
    product_id: int
    product_title: Optional[str] = None
    units_sold: int
    units_returned: int
    return_rate: float
    total_refund_amount: float


class ReturnsMonthlyTrend(BaseModel):
    month: str
    returns_count: int


class ReturnsDateRange(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ReturnsInsightsResponse(BaseModel):
    scope: str  # "store-wide" | "product" | "sku"
    product_id: Optional[int] = None
    product_sku_id: Optional[str] = None
    date_range: ReturnsDateRange

    total_units_sold: int
    total_units_returned: int
    overall_return_rate: float
    total_refund_amount: float
    dispute_rate: float
    refund_request_rate: float

    return_reason_breakdown: List[ReturnReasonBreakdown]
    monthly_trend: List[ReturnsMonthlyTrend]
    recommendations: List[str]


class ReturnsDashboardResponse(BaseModel):
    date_range: ReturnsDateRange
    top_products_by_return_rate: List[ProductReturnStats]
