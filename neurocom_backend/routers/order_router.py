
from fastapi import APIRouter, Depends
from neurocom_backend.services.order_service import store_new_order, update_order_service, get_all_orders_by_customer_id, get_order_by_id, delete_order_by_id
from neurocom_backend.database.models.order import Order
from neurocom_backend.database.connection import get_session
from sqlmodel import Session
from typing import Annotated
from uuid import UUID

router  = APIRouter(prefix="/order",tags=["Order"])

@router.get('/')
def home():
    return {"message": "Order Router"}

@router.post('/create_order')
async def create_order(order: Order, db: Annotated[Session, Depends(get_session)]):
    new_order = store_new_order(order=order, db=db)
    return {"new order": new_order}

@router.put('/update_order')
async def update_order(updated_order: Order, db: Annotated[Session, Depends(get_session)]):
    updated_order = update_order_service(updated_order=updated_order, db=db)
    return {"updated order": updated_order}

@router.get('/get_customer_orders')
async def get_customer_orders(customer_id: UUID, db: Annotated[Session, Depends(get_session)]):
    orders = get_all_orders_by_customer_id(customer_id=customer_id, db=db)
    return {"orders": orders}

@router.get('/get_order/{order_id}')
async def get_order(order_id: UUID, db: Annotated[Session, Depends(get_session)]):
    order = get_order_by_id(order_id=order_id, db=db)
    return {"order": order}

@router.delete('/delete_order/{order_id}')
async def delete_order(order_id: UUID, db: Annotated[Session, Depends(get_session)]):
    deleted_order = delete_order_by_id(order_id=order_id, db=db)
    return {"deleted order": deleted_order}