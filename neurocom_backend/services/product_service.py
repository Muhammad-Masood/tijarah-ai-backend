from neurocom_backend.database.models.product import Product
from neurocom_backend.database.connection import get_session
from fastapi import Depends, HTTPException
from typing import Annotated
from sqlmodel import Session, select
from uuid import UUID
from datetime import datetime

def store_new_product(product: Product, db: Session):
    new_product = Product(title=product.title, description=product.description, price=product.price, image=product.image, category=product.category)
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product

def update_product_service(product: Product, db: Session):
    product_db = db.exec(select(Product).where(Product.id == product.id)).first()
    if product_db is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product_db.title = product.title
    product_db.description = product.description
    product_db.price = product.price
    # product_db.images = product.images
    product.image = product.image
    product.category = product.category
    db.commit()
    db.refresh(product_db)
    return product_db


def delete_product_by_id(product_id: UUID, db: Session):
    product = db.exec(select(Product).where(Product.id == product_id)).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return product

def get_product_by_id(product_id: UUID, db: Session):
    product = db.exec(select(Product).where(Product.id == product_id)).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

def get_all_products(db: Session):
    products = db.exec(select(Product)).all()
    return products