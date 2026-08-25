from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from neurocom_backend.database.connection import get_session
from neurocom_backend.database.models.merchant import Merchant
from neurocom_backend.database.models.user import UserRole
from neurocom_backend.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _resolve_merchant(token: str, db: Session, credentials_exception: Exception) -> Merchant:
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


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_session)],
) -> Merchant:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    return _resolve_merchant(token, db, credentials_exception)


def get_current_user_ws(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_session)],
) -> Merchant:
    """WebSocket counterpart to get_current_user. OAuth2PasswordBearer (and
    FastAPI's other SecurityBase-derived schemes) hard-require an HTTP
    Request in their __call__ signature and raise a bare TypeError if
    resolved against a websocket connection instead — so this reads the
    Authorization header directly off the handshake rather than going
    through Depends(oauth2_scheme)."""
    credentials_exception = WebSocketException(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Could not validate credentials",
    )
    auth_header = websocket.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise credentials_exception
    token = auth_header.split(" ", 1)[1]
    return _resolve_merchant(token, db, credentials_exception)


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
