---
kind: configuration_system
name: Environment-Based Configuration via python-dotenv
category: configuration_system
scope:
    - '**'
source_files:
    - neurocom_backend/utils/settings.py
    - .env.example
    - neurocom_backend/main.py
    - neurocom_backend/database/connection.py
    - neurocom_backend/routers/daraz_router.py
    - neurocom_backend/mcp_server/client.py
    - neurocom_backend/agents/main.py
---

## What system/approach is used

The application uses a flat, environment-variable–driven configuration approach powered by `python-dotenv`. There is no centralized typed settings model (e.g. Pydantic `BaseSettings`); instead, each module that needs configuration calls `load_dotenv()` at import time and reads values directly with `os.getenv()`, typically providing defaults for non-secret values.

## Key files and packages

- `neurocom_backend/utils/settings.py` — the single shared configuration module. It calls `load_dotenv()` immediately on import so that constants like `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, Redis connection parameters (`REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_SSL`), cache TTLs (`DARAZ_CACHE_TTL_SECONDS`, `SHOPIFY_CACHE_TTL_SECONDS`), Supabase credentials (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PRODUCT_BUCKET`), and Shopify keys are available to any importer regardless of import order. CORS origins are hard-coded as `ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:3001']` here.
- `.env.example` — documents every required/optional environment variable in one place (OpenAI, Daraz, Shopify, DB, JWT, SQL echo, Supabase).
- `neurocom_backend/main.py` — top-level entry point; also calls `load_dotenv()` before creating the FastAPI app and mounts routers/middleware.
- `neurocom_backend/database/connection.py` — loads DB connection string and `SQL_ECHO` flag from env to configure SQLAlchemy/SQLModel engine.
- `neurocom_backend/routers/daraz_router.py`, `forecast_router.py`, `inisghts.router.py`, `mcp_server/client.py`, `agents/main.py` — each call `load_dotenv()` locally because they may be imported before the app process reaches `main.py`.
- `pyproject.toml` — declares `python-dotenv` indirectly through its transitive dependencies (FastAPI/Uvicorn ecosystem) but does not declare it explicitly; runtime loading relies on the installed package.

## Architecture and conventions

1. **Dotenv-first, no config file format.** The project does not use YAML/TOML/JSON config files for runtime settings. All runtime values come from environment variables loaded from a `.env` file (or the process environment). Secrets (API keys, DB strings) are expected to be injected via environment; non-secrets have sensible defaults.
2. **Eager dotenv loading.** Every module that consumes env vars calls `load_dotenv()` at module level. The comment in `utils/settings.py` explicitly explains this pattern: modules may be imported before `main.py`'s own `load_dotenv()` runs, so each consumer ensures the `.env` is loaded before reading `os.getenv()`.
3. **Flat key namespace.** All configuration keys are uppercase strings (e.g. `DB_CONNECTION_STRING`, `SHOPIFY_API_KEY`, `REDIS_SSL`). There is no namespacing or hierarchical structure beyond the variable name itself.
4. **Type coercion at read time.** Non-string values are parsed inline where consumed: booleans are normalized via `.strip().lower() in ("1", "true", "yes")` (used for `REDIS_SSL`, `SQL_ECHO`); integers via `int(os.getenv(...))`; trailing slashes stripped for URLs (`SUPABASE_URL.rstrip("/")`).
5. **Hardcoded fallbacks for non-critical settings.** CORS allowed origins are fixed in code rather than env-driven. Cache TTLs default to 86400 seconds if not provided.
6. **No validation layer.** Values are read raw; there is no schema validation, type checking, or error handling around missing env vars. A missing secret will surface as a downstream error when the value is used (e.g. database connection fails).
7. **Per-module responsibility.** Unlike a centralized settings object, each subsystem (database, Daraz router, MCP client, agents) independently loads dotenv and reads the keys it needs.

## Conventions and constraints

- **Secrets must be supplied via environment** (`.env` or process env): `SECRET_KEY`, `DB_CONNECTION_STRING`, `OPENAI_API_KEY`, `DARAZ_APP_KEY`, `DARAZ_APP_SECRET`, `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`, `SUPABASE_SECRET_KEY`, `GROQ_API_KEY`, `APP_CALLBACK_URL`. These have no defaults and are expected to be present at runtime.
- **Non-secret flags accept explicit boolean forms**: `REDIS_SSL` and `SQL_ECHO` accept `1`, `true`, `yes` (case-insensitive, whitespace-trimmed) as truthy values; everything else is falsy.
- **Cache TTLs default to 24 hours** (`86400`) for both Daraz and Shopify unless overridden by `DARAZ_CACHE_TTL_SECONDS` / `SHOPIFY_CACHE_TTL_SECONDS`.
- **CORS origins are pinned to localhost development URLs** (`http://localhost:3000`, `http://localhost:3001`) in code; changing them requires editing `utils/settings.py`.
- **Database URL is trimmed** of trailing slashes before use (`SUPABASE_URL` is handled similarly), ensuring consistent base paths.
- **No per-environment config files** (no `.env.production`, `.env.development` switching logic); the same `.env` file is loaded everywhere.
- **Dependency injection of settings is not used**; modules access configuration through global `os.getenv()` calls after `load_dotenv()` has run.