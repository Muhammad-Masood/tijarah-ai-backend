# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install dependencies: `poetry install`
- Run the dev server: `make run` (equivalent to `poetry run uvicorn neurocom_backend.main:app --host 0.0.0.0 --port 8000 --reload`)
- Create/promote an admin account (no public signup endpoint creates admins by design):
  `poetry run python -m neurocom_backend.scripts.create_admin --email <email> --password <pw> --full-name "<name>"`

There is no test suite configured yet (`tests/` only contains an empty `__init__.py`, and no test framework is a dependency in `pyproject.toml`). Don't invent `pytest` commands — verify changes by running the server and hitting the relevant endpoint(s) instead.

## Environment

Copy `.env.example` to `.env` and fill in values. Key vars: `DB_CONNECTION_STRING` (Postgres), `SECRET_KEY` (JWT signing *and* Fernet token encryption — see below), `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `OPENAI_API_KEY`, `DARAZ_APP_KEY`/`DARAZ_APP_SECRET`/`DARAZ_API_URL`/`DARAZ_AUTH_URL`, `APP_CALLBACK_URL`. Redis vars (`REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_SSL`) are optional and default to a local, unauthenticated Redis instance.

`neurocom_backend/utils/settings.py` force-calls `load_dotenv()` at import time (not just in `main.py`) specifically to avoid import-order bugs — other modules import settings constants before `main.py`'s own `load_dotenv()` runs.

## Architecture

FastAPI app (`neurocom_backend/main.py`) in a router → service → database/models layering:

- **Routers** (`routers/`) — HTTP surface only; parse input, call a service, return it.
- **Services** (`services/`) — business logic; take/return either SQLModel table instances or plain dicts/Pydantic models, not FastAPI-specific types.
- **Database models** (`database/models/`) — each file (e.g. `merchant.py`, `marketplace.py`) defines both the SQLModel `table=True` entity *and* its Pydantic `Create`/`Read` DTOs side by side, all re-exported through `database/models/__init__.py`. Import models from that package, not the individual files.

No Alembic — `perform_migration()` in `database/connection.py` just calls `SQLModel.metadata.create_all(engine)` on startup (see the `lifespan` in `main.py`). This only creates missing tables; it does not handle column renames/type changes/drops. Any destructive schema change needs manual DB intervention.

### Auth

JWT bearer auth (`utils/security.py`: `create_access_token`/`decode_access_token`) resolved via `dependencies.get_current_user`, which loads a `Merchant` (not `Customer` — `Customer` exists as a model but has no auth flow wired up). Auth is applied **per-router at include time** in `main.py` (`app.include_router(x_router.router, dependencies=require_auth)`), not per-route — `auth_router` is the only one excluded. `require_admin` (`dependencies.py`) gates admin-only routes (e.g. marketplace CRUD in `marketplace_router.py`), checking `Merchant.role`.

### Marketplace integration model

`Marketplace`/`MarketplaceConnection` (`database/models/marketplace.py`) are a generic abstraction over third-party marketplace connections — currently only Daraz is implemented, identified at runtime via `marketplace_service.is_daraz_marketplace()` (matched by slug/name, not a hardcoded FK/type column). `MarketplaceConnection.encrypted_access_token` is encrypted with Fernet (`utils/security.py: encrypt_value`/`decrypt_value`, key derived from `SECRET_KEY`), not stored in plaintext.

Daraz-specific API calls (`services/daraz_service.py`) go through a **vendored, modified copy** of the Lazop SDK at `neurocom_backend/python/lazop/` — this is not the pip package, so don't `pip install lazop-sdk` to "fix" imports. `daraz_router.py` endpoints additionally require a per-request `X-Daraz-Access-Token` header (the encrypted marketplace token, decrypted via the `get_daraz_access_token` dependency) *on top of* the merchant's JWT — two independent credentials per request.

### Caching

`utils/redis_cache.py`'s `get_or_refresh()` implements cache-aside + stale-while-revalidate: the first call fetches+transforms+caches; every subsequent call returns the cached (already-transformed) value immediately while a background thread re-fetches the *raw* payload and only re-runs the (expensive) `transform_fn` if a hash comparison shows the raw data actually changed. Read the module docstring before touching this — the raw-vs-transformed hashing split is deliberate (transform is CPU-bound and would block the foreground thread under the GIL if done inline on every background check). `services/daraz_service.get_all_products` is the reference usage.

### MCP servers (two distinct things named "mcp")

- `mcp_server/customer_support/main.py` — a `FastMCP` **tool server** (`add`, `cancel_customer_order`, etc.) exposed over SSE and mounted into the main app at `/mcp` (`app.mount('/mcp', sse_app)` in `main.py`).
- `mcp_server/client.py` — `MCPClient`, an MCP **client** wrapping an OpenAI-compatible chat-completions call (currently pointed at Groq's endpoint) that discovers and invokes tools from the SSE server above. Used by `routers/customer_support_router.py`'s `/customer_support/chat/{prompt}` endpoint.

`agents/` is largely scaffolding-in-progress (`agents/main.py` sets up a separate OpenRouter-backed client; `agents/instructions.py:get_reviews_analysis_instructions` is currently a stub).

### Reviews analysis pipeline

`services/reviews_service.py` is a map-reduce LLM pipeline over scraped Daraz reviews: dedupe → embed + KMeans cluster (any scale, not just the first N reviews) → per-cluster LLM summary (map) → cross-cluster synthesis (reduce), using structured output (Pydantic schemas via function-calling) rather than parsing fenced JSON. The module docstring lays out the design rationale — read it before changing the pipeline shape.

### Insights / forecast

`routers/inisghts.router.py` (filename typo is real, not a typo to fix blindly — check for external references first) and `routers/forecast_router.py`, backed by `services/insights.service.py` and `services/inventory.py`, currently operate on generated mock data (`get_mock_daraz_data`, `generate_mock_orders`) — not yet wired to a merchant's real `MarketplaceConnection` data.
