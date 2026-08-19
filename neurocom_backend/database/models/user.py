from sqlmodel import SQLModel, Field, Relationship
from pydantic import BaseModel, EmailStr
from uuid import uuid4, UUID
from typing import Optional, List, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from .order import Order

class UserRole(str, Enum):
    admin = "admin"
    user = "user"

class UserBase(SQLModel):
    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    full_name: str = Field(nullable=False, min_length=3, max_length=50)
    email: EmailStr = Field(nullable=False, unique=True, index=True)
    password: str = Field(nullable=False, min_length = 4)
    role: UserRole = Field(default=UserRole.user, nullable=False)

class Customer(UserBase, table=True):
    address: Optional[str] = Field(default=None, min_length=3)
    phone_number: Optional[str] = Field(default=None, min_length=6)
    # order_id: UUID = Field(foreign_key="order.id", nullable=False)
    orders: List["Order"] = Relationship(back_populates="customer")

class CustomerCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=4)
    address: Optional[str] = Field(default=None, min_length=3)
    phone_number: Optional[str] = Field(default=None, min_length=6)

class CustomerRead(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    role: UserRole
    address: Optional[str] = None
    phone_number: Optional[str] = None

