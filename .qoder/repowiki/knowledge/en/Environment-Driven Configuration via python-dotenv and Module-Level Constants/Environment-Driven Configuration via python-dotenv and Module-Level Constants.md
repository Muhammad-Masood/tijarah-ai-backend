---
kind: configuration_system
name: Environment-Driven Configuration via python-dotenv and Module-Level Constants
category: configuration_system
scope:
    - '**'
source_files:
    - neurocom_backend/utils/settings.py
    - neurocom_backend/database/connection.py
    - neurocom_backend/main.py
    - .env.example
    - pyproject.toml
---

## What system/approach is used

The application uses a minimal, environment-variable-driven configuration approach built on `python-dotenv` (`load_dotenv`) with module-level constants. There is no centralized settings class, Pydantic `BaseSettings`, or external config file format (YAML/JSON/TOML). All runtime configuration is read from the process environment at import time.

## Key files and packages

- `neurocom_backend/utils/settings.py` — single source of truth for all application-wide configuration constants. Calls `load_dotenv()` at module import to guarantee `.env` is loaded before any other module reads its values.
- `neurocom_backend/database/connection.py` — loads `.env` again and builds the SQLAlchemy engine using `DB_CONNECTION_STRING` and `SQL_ECHO`.
- `neurocom_backend/main.py` — calls `load_dotenv()` at startup and imports `ALLOWED_ORIGINS` from `settings` to configure CORS.
- `.env.example` — documents every required/optional environment variable with placeholder values.
- `pyproject.toml` — declares runtime dependencies (e.g., `redis`, `psycopg2-binary`, `openai`) that are consumed via env vars; no Poetry `[tool.poetry.scripts]` or config sections.

## Architecture and conventions

1. **Single settings module**: All configuration keys are defined as top-level constants in `utils/settings.py`. Consumers import only the symbols they need (e.g., `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REDIS_*`, `SHOPIFY_*`, `SUPABASE_*`, `WHATSAPP_*`).

2. **Import-time loading**: `settings.py` calls `load_dotenv()` immediately when imported. The comment explains this is necessary because modules may be imported before `main.py`'s own `load_dotenv()` call runs. This avoids a race condition where a dependency is imported during app startup before `.env` is loaded.

3. **No defaults for secrets**: Sensitive values (`SECRET_KEY`, `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, `SUPABASE_SECRET_KEY`, `WHATSAPP_ACCESS_TOKEN`, `DB_CONNECTION_STRING`) are read with `os.getenv("...")` and have no default — missing them will raise an error at first use. Non-sensitive or optional values provide sensible defaults (e.g., `JWT_ALGORITHM="HS256"`, `REDIS_HOST="localhost"`, `REDIS_PORT=6379`, `SUPABASE_PRODUCT_BUCKET="product-images"`, `WHATSAPP_VERIFY_TOKEN="tijarah_whatsapp_verify_2026"`).

4. **Boolean parsing convention**: Boolean-like env vars are normalized by comparing against a set of truthy strings: `os.getenv("X", "false").strip().lower() in ("1", "true", "yes")`. Used for `REDIS_SSL` and `SQL_ECHO`.

5. **Type coercion at load time**: Numeric values are cast to `int` at import time (`ACCESS_TOKEN_EXPIRE_MINUTES`, `REDIS_PORT`, `DARAZ_CACHE_TTL_SECONDS`, `SHOPIFY_CACHE_TTL_SECONDS`), so downstream code receives typed values without repeated parsing.

6. **Trailing-slash stripping**: `SUPABASE_URL` is stripped of trailing slashes via `.rstrip("/")` to prevent double-slash URL construction.

7. **Dual `load_dotenv()` calls**: Both `main.py` and `database/connection.py` call `load_dotenv()` independently. While redundant, it ensures `.env` is available regardless of import order.

8. **Configuration consumption pattern**: Each subsystem imports only what it needs:
   - `utils/security.py` → `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
   - `utils/redis_cache.py` → `REDIS_*` variables
   - `services/shopify_service.py` → `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, `SHOPIFY_CACHE_TTL_SECONDS`
   - `services/storage_service.py` → `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PRODUCT_BUCKET`
   - `services/whatsapp_service.py` → `WHATSAPP_*` variables
   - `routers/whatsapp_support_router.py` → `WHATSAPP_VERIFY_TOKEN`
   - `main.py` → `ALLOWED_ORIGINS`

## Conventions and constraints

- **All configuration lives in environment variables** — there are no YAML/JSON/TOML config files, no database-backed config tables, and no CLI flags for configuration.
- **`.env` is the only local configuration mechanism**; production deployments must supply these variables through their runtime environment (container env, platform secret store, etc.).
- **Secrets have no defaults** — omitting a required secret causes a failure at first access, making missing configuration visible early.
- **Feature toggles are absent** — behavior is not gated by feature-flag env vars; toggling functionality requires code changes.
- **CORS origins are hardcoded** in `settings.py` as a Python list (`['http://localhost:3000', 'http://localhost:3001']`) rather than being read from env, which is a deviation from the rest of the configuration style.
- **Database migrations run at startup** via `perform_migration()` in the FastAPI lifespan, using the connection string from env — there is no separate migration tooling invoked outside the app lifecycle.