from neurocom_backend.database.models.order import Order, OrderStatus
from neurocom_backend.database.connection import get_session
from fastapi import Depends, HTTPException
from typing import Annotated
from sqlmodel import Session, select
from uuid import UUID
from datetime import datetime

def store_new_order(order: Order, db: Session):
    new_order = Order(customer_id=order.customer_id, total_amount=order.total_amount, status=order.status, products_order=order.products_order)
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return new_order

def update_order_service(order: Order, db: Session):
    order_db = db.exec(select(Order).where(Order.id == order.id)).first()
    if order_db is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order_db.total_amount = order.total_amount
    order_db.status = order.status
    order_db.products_order = order.products_order
    order_db.updated_at = datetime.now()
    db.commit()
    db.refresh(order_db)
    return order_db


def delete_order_by_id(order_id: UUID, db: Session):
    order = db.exec(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return order


def get_order_by_id(order_id: UUID, db: Session):
    order = db.exec(select(Order).where(Order.id == order_id)).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def get_all_orders_by_customer_id(customer_id: UUID, db: Session):
    orders = db.exec(select(Order).where(Order.customer_id == customer_id)).all()
    return orders