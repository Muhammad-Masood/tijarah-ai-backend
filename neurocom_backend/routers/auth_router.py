from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.merchant import Merchant, MerchantCreate, MerchantRead
from neurocom_backend.dependencies import get_current_user
from neurocom_backend.schemas.auth import Token
from neurocom_backend.services.auth_service import authenticate_merchant
from neurocom_backend.services.user_service import store_new_user
from neurocom_backend.utils.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=MerchantRead)
async def create_merchant(user: MerchantCreate, db: Annotated[Session, Depends(get_session)]):
    new_user = store_new_user(db=db, merchant=user)
    return new_user


@router.post("/login", response_model=Token)
async def login_merchant(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_session)],
):
    merchant = authenticate_merchant(db, form_data.username, form_data.password)
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(subject=str(merchant.id), account_type="merchant")
    return Token(access_token=access_token)


@router.get("/me", response_model=MerchantRead)
async def read_current_user(current_user: Annotated[Merchant, Depends(get_current_user)]):
    return current_user
