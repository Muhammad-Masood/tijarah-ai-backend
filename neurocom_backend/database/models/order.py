from sqlmodel import SQLModel, Field, Relationship, ForeignKey, DateTime
from uuid import uuid4, UUID
from typing import Optional, List, TYPE_CHECKING
from enum import Enum as PyEnum
from datetime import datetime

# if TYPE_CHECKING:
from .user import Customer


class OrderStatus(PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURN_REQUESTED = "return_requested"
    RETURNED = "returned"
    REFUNDED = "refunded"

class Order(SQLModel, table=True):
    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    total_amount: float = Field(default=0)
    status: OrderStatus = Field(default=OrderStatus.PENDING, index=True)
    created_at: datetime = Field(default=datetime.now())
    updated_at: datetime = Field(default=datetime.now())
    # Relationships
    customer_id: UUID|None = Field(default=None, foreign_key="customer.id", index=True)
    customer: Customer|None = Relationship(back_populates="orders")
    products_order: list["ProductOrder"] = Relationship(back_populates="order")

class ProductOrder(SQLModel, table=True):
    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    product_id: UUID = Field(foreign_key="product.id", nullable=False)
    quantity: int = Field(default=0)
    sub_total: float = Field(default=0)
    order_id: UUID|None  = Field(foreign_key="order.id", default=None)
    # Relationships
    order: Order|None = Relationship(back_populates="products_order")