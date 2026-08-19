from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.user import UserRole
from neurocom_backend.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_session)],
) -> Merchant:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        subject: str | None = payload.get("sub")
        account_type: str | None = payload.get("type")
        if subject is None or account_type != "merchant":
            raise credentials_exception
        merchant_id = UUID(subject)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise credentials_exception
    return merchant


def require_roles(*roles: UserRole):
    def dependency(current_user: Annotated[Merchant, Depends(get_current_user)]) -> Merchant:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user
    return dependency


require_admin = require_roles(UserRole.admin)
