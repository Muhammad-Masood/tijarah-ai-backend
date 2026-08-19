from sqlmodel import Session, select

from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.utils.security import verify_password

def authenticate_merchant(db: Session, email: str, password: str) -> Merchant | None:
    merchant = db.exec(select(Merchant).where(Merchant.email == email)).first()
    if not merchant or not verify_password(password, merchant.password):
        return None
    return merchant
