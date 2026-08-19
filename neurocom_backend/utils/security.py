from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import jwt
from dotenv import load_dotenv

from neurocom_backend.utils.settings import SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

_: bool = load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(subject: str, account_type: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "type": account_type, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


def _get_fernet() -> Fernet:
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured")
    key = urlsafe_b64encode(sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
