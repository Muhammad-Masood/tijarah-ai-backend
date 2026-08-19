from pydantic import BaseModel
from typing import List, Optional

class Sku(BaseModel):
    SellerSku: str
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
