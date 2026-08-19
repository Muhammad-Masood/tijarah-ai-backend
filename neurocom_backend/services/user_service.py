from sqlmodel import Session, select
from neurocom_backend.database.models.user import UserBase, Customer, CustomerCreate, UserRole
from neurocom_backend.database.connection import get_session
from fastapi import Depends, HTTPException
from neurocom_backend.utils.security import hash_password
from neurocom_backend.database.models.merchant import Merchant, MerchantCreate

def store_new_user(db: Session, merchant: MerchantCreate) -> Merchant:
    merchant_exists = db.exec(select(Merchant).where(Merchant.email == merchant.email)).first()
    if merchant_exists:
        raise HTTPException(status_code=400, detail="Merchant already exists")
    hashed_password: str = hash_password(merchant.password)
    new_merchant = Merchant(
        full_name=merchant.full_name,
        business_name=merchant.business_name,
        email=merchant.email,
        password=hashed_password,
        phone_number=merchant.phone_number,
        role=UserRole.user,
    )
    db.add(new_merchant)
    db.commit()
    db.refresh(new_merchant)
    return new_merchant
