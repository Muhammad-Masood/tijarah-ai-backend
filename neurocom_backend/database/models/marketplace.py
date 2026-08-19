from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import Column, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .merchant import Merchant


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Marketplace(SQLModel, table=True):
    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    name: str = Field(nullable=False, unique=True, min_length=2, max_length=100, index=True)
    slug: str = Field(nullable=False, unique=True, index=True, max_length=100)
    url: str = Field(sa_column=Column(String(2048), nullable=False))
    logo_url: str = Field(sa_column=Column(String(2048), nullable=False))
    connections: List["MarketplaceConnection"] = Relationship(back_populates="marketplace")


class MarketplaceConnection(SQLModel, table=True):
    __tablename__ = "marketplace_connection"
    __table_args__ = (
        UniqueConstraint("merchant_id", "marketplace_id", name="uq_merchant_marketplace"),
    )

    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    merchant_id: UUID = Field(foreign_key="merchant.id", nullable=False, index=True)
    marketplace_id: UUID = Field(foreign_key="marketplace.id", nullable=False, index=True)
    encrypted_access_token: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    connected_at: datetime = Field(default_factory=utc_now)

    marketplace: Optional[Marketplace] = Relationship(back_populates="connections")
    merchant: Optional["Merchant"] = Relationship(back_populates="marketplace_connections")


class MarketplaceCreate(BaseModel):
    name: str = PydanticField(min_length=2, max_length=100)
    url: str = PydanticField(min_length=3, max_length=2048)
    logo_url: str = PydanticField(min_length=3, max_length=2048)
    slug: Optional[str] = PydanticField(default=None, min_length=2, max_length=100)


class MarketplaceUpdate(BaseModel):
    name: Optional[str] = PydanticField(default=None, min_length=2, max_length=100)
    url: Optional[str] = PydanticField(default=None, min_length=3, max_length=2048)
    logo_url: Optional[str] = PydanticField(default=None, min_length=3, max_length=2048)
    slug: Optional[str] = PydanticField(default=None, min_length=2, max_length=100)


class MarketplaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    url: str
    logo_url: str
    is_connected: bool = False


class ConnectMarketplaceRequest(BaseModel):
    code: Optional[str] = None
    access_token: Optional[str] = None


class MarketplaceConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    marketplace_id: UUID
    merchant_id: UUID
    connected_at: datetime
    marketplace: Optional[MarketplaceRead] = None
