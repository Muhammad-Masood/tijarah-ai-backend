from fastapi import APIRouter, Depends
from neurocom_backend.services.product_service import store_new_product, update_product_service, get_all_products, get_product_by_id, delete_product_by_id
from neurocom_backend.database.models.product import Product
from neurocom_backend.database.connection import get_session
from sqlmodel import Session
from typing import Annotated
from uuid import UUID

router  = APIRouter(prefix="/product",tags=["Product"])

@router.get('/')
def home():
    return {"message": "Product Router"}

@router.post('/create_product')
async def create_product(product: Product, db: Annotated[Session, Depends(get_session)]):
    new_product = store_new_product(product=product, db=db)
    return {"new product": new_product}

@router.put('/update_product')
async def update_product(updated_product: Product, db: Annotated[Session, Depends(get_session)]):
    updated_product = update_product_service(updated_product=updated_product, db=db)
    return {"updated product": updated_product}

@router.get('/get_product/{product_id}')
async def get_product(product_id: UUID, db: Annotated[Session, Depends(get_session)]):
    product = get_product_by_id(product_id=product_id, db=db)
    return {"product": product}

@router.get('/get_products')
async def get_products(db: Annotated[Session, Depends(get_session)]):
    products = get_all_products(db=db)
    return {"products": products}

@router.delete('/delete_product/{product_id}')
async def delete_product(product_id: UUID, db: Annotated[Session, Depends(get_session)]):
    deleted_product = delete_product_by_id(product_id=product_id, db=db)
    return {"deleted product": deleted_product}