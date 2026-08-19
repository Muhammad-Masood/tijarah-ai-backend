from sqlmodel import SQLModel, Field, Relationship
from uuid import uuid4, UUID
from typing import Optional, List, TYPE_CHECKING


# class ProductImage(SQLModel, table=True):
#     id: UUID = Field(primary_key=True, default_factory=uuid4, index=True)
#     url: str = Field(nullable=False)
#     product_id: UUID = Field(foreign_key="product.id", nullable=False)
#     # Relationships
#     product: Optional["Product"] = Relationship(back_populates="images")

class Product(SQLModel, table=True):
    id: Optional[UUID] = Field(primary_key=True, default_factory=uuid4, index=True)
    title: str = Field(nullable=False, min_length=3)
    price: float = Field(nullable=False)
    description: str
    image: str
    category: str
    # Relationships
    # images: list["ProductImage"] = Relationship(back_populates="product")