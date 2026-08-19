from sqlmodel import Field, Relationship
from pydantic import BaseModel, EmailStr
from uuid import UUID
from typing import Optional, List, TYPE_CHECKING

from .user import UserBase, UserRole

if TYPE_CHECKING:
    from .marketplace import MarketplaceConnection

class Merchant(UserBase, table=True):
    business_name: str = Field(nullable=False, min_length=2, max_length=100)
    phone_number: Optional[str] = Field(default=None, min_length=6)
    marketplace_connections: List["MarketplaceConnection"] = Relationship(back_populates="merchant")

class MerchantCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=50)
    business_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=4)
    phone_number: Optional[str] = Field(default=None, min_length=6)

class MerchantRead(BaseModel):
    id: UUID
    full_name: str
    business_name: str
    email: EmailStr
    role: UserRole
    phone_number: Optional[str] = None
