from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField, SQLModel

from .marketplace import utc_now


class ProductExpense(SQLModel, table=True):
    """Merchant-defined expense/cost for a specific product SKU.

    Stores costs like product cost, fuel, packaging, etc. that are deducted
    from net revenue when calculating actual net profit.
    """
    __tablename__ = "product_expense"

    id: Optional[UUID] = SQLField(primary_key=True, default_factory=uuid4, index=True)
    merchant_id: UUID = SQLField(foreign_key="merchant.id", nullable=False, index=True)
    sku_id: str = SQLField(nullable=False, index=True, max_length=255)
    platform: str = SQLField(nullable=False, max_length=50)  # daraz, shopify, both
    category: str = SQLField(nullable=False, max_length=100)  # product_cost, fuel, packaging, etc.
    amount: float = SQLField(nullable=False)
    description: Optional[str] = SQLField(default=None, max_length=500)
    created_at: datetime = SQLField(default_factory=utc_now)
    updated_at: Optional[datetime] = SQLField(default=None)


# ---------------------------------------------------------------------------
# Pydantic schemas for API request/response
# ---------------------------------------------------------------------------

class ProductExpenseCreate(BaseModel):
    sku_id: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=50)
    category: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    description: Optional[str] = Field(default=None, max_length=500)


class ProductExpenseUpdate(BaseModel):
    sku_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    platform: Optional[str] = Field(default=None, min_length=1, max_length=50)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    amount: Optional[float] = Field(default=None, gt=0)
    description: Optional[str] = Field(default=None, max_length=500)


class ProductExpenseRead(BaseModel):
    id: UUID
    merchant_id: UUID
    sku_id: str
    platform: str
    category: str
    amount: float
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
