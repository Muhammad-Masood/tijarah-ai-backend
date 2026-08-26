import os
from dotenv import load_dotenv

# Other modules import settings for their own env-derived constants at
# import time, which can happen before their own load_dotenv() call runs
# (e.g. main.py imports routers -> services -> settings before it calls
# load_dotenv() itself). Loading here guarantees these constants are
# resolved from .env regardless of import order.
load_dotenv()

ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:3001']

SECRET_KEY = os.getenv("SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_USERNAME = os.getenv("REDIS_USERNAME") or None
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_SSL = os.getenv("REDIS_SSL", "false").strip().lower() in ("1", "true", "yes")
DARAZ_CACHE_TTL_SECONDS = int(os.getenv("DARAZ_CACHE_TTL_SECONDS", str(24 * 60 * 60)))

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_CACHE_TTL_SECONDS = int(os.getenv("SHOPIFY_CACHE_TTL_SECONDS", str(24 * 60 * 60)))