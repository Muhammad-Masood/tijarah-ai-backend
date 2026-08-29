from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional


class ShopifyImage(BaseModel):
    src: str
    altText: Optional[str] = None


class ShopifyVariant(BaseModel):
    id: str
    title: str
    price: Optional[str] = None
    inventoryQuantity: Optional[int] = None


class ShopifyProductCategory(BaseModel):
    id: str
    name: str


class ShopifyProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    handle: Optional[str] = None
    status: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    productType: Optional[str] = None
    totalInventory: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    category: Optional[ShopifyProductCategory] = None
    images: List[ShopifyImage] = Field(default_factory=list)
    variants: List[ShopifyVariant] = Field(default_factory=list)


class ShopifyGetAllProductsResponse(BaseModel):
    products: List[ShopifyProduct]


class ShopifyGetProductResponse(BaseModel):
    product: Optional[ShopifyProduct] = None


class ShopifyCollection(BaseModel):
    id: str
    title: str
    handle: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None


class ShopifyGetAllCollectionsResponse(BaseModel):
    collections: List[ShopifyCollection]


class ShopifyTaxonomyCategory(BaseModel):
    id: str
    name: str
    fullName: Optional[str] = None


class ShopifyGetAllCategoriesResponse(BaseModel):
    categories: List[ShopifyTaxonomyCategory]


class ShopifyOrderLineItemVariant(BaseModel):
    id: str
    title: Optional[str] = None


class ShopifyOrderLineItem(BaseModel):
    id: str
    title: str
    quantity: int
    price: Optional[str] = None
    currency: Optional[str] = None
    variant: Optional[ShopifyOrderLineItemVariant] = None


class ShopifyOrderCustomer(BaseModel):
    id: Optional[str] = None
    displayName: Optional[str] = None
    email: Optional[str] = None


class ShopifyOrderMoney(BaseModel):
    amount: str
    currencyCode: str


class ShopifyOrder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    processedAt: Optional[str] = None
    displayFinancialStatus: Optional[str] = None
    displayFulfillmentStatus: Optional[str] = None
    totalPriceSet: Optional[dict] = None
    customer: Optional[ShopifyOrderCustomer] = None
    lineItems: List[ShopifyOrderLineItem] = Field(default_factory=list)
    totalAmount: Optional[str] = None
    currencyCode: Optional[str] = None


class ShopifyGetAllOrdersResponse(BaseModel):
    orders: List[ShopifyOrder]


class ShopifyMediaInput(BaseModel):
    originalSource: str
    alt: Optional[str] = None
    mediaContentType: str = "IMAGE"


class ShopifyProductCreate(BaseModel):
    title: str
    descriptionHtml: str
    vendor: Optional[str] = None
    tags: Optional[List[str]] = None
    collectionsToJoin: Optional[List[str]] = None
    category: Optional[str] = None
    inventory: int
    price: str
    images: Optional[List[ShopifyMediaInput]] = None
