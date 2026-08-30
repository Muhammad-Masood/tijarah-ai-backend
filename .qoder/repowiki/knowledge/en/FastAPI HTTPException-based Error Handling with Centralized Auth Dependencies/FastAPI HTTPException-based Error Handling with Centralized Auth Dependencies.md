---
kind: error_handling
name: FastAPI HTTPException-based Error Handling with Centralized Auth Dependencies
category: error_handling
scope:
    - '**'
source_files:
    - neurocom_backend/dependencies.py
    - neurocom_backend/main.py
    - neurocom_backend/routers/auth_router.py
    - neurocom_backend/routers/daraz_router.py
    - neurocom_backend/routers/customer_support_router.py
    - neurocom_backend/routers/reviews_router.py
    - neurocom_backend/routers/shopify_router.py
    - neurocom_backend/routers/product_listing_router.py
    - neurocom_backend/routers/storage_router.py
    - neurocom_backend/utils/security.py
---

## Overview

The repository uses FastAPI's built-in `HTTPException` and `WebSocketException` as the primary error signaling mechanism. There is no custom exception hierarchy, no centralized exception-to-JSON mapper, and no global `exception_handler` registered on the app. Errors are raised inline in routers and dependencies and let FastAPI convert them to JSON responses automatically.

## Core Components

### Authentication & Authorization Errors (`neurocom_backend/dependencies.py`)

All auth-related failures funnel through two shared exceptions created inside dependency functions:

- `get_current_user` builds a local `HTTPException(status_code=401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})` and raises it for invalid JWTs, missing subjects, non-merchant accounts, or unknown merchant IDs. The same pattern is used by `_resolve_merchant`, which centralizes token decoding via `utils.security.decode_access_token` and re-raises the same `credentials_exception` on `jwt.PyJWTError` / `ValueError`.
- `get_current_user_ws` is the WebSocket counterpart; it reads the `Authorization` header directly (because `OAuth2PasswordBearer` requires an HTTP request) and raises a `WebSocketException(code=WS_1008_POLICY_VIOLATION, reason="Could not validate credentials")`.
- `require_roles(*roles)` is a reusable role-checker dependency that raises `HTTPException(403_FORBIDDEN, detail="You do not have permission to perform this action")` when `current_user.role` is not in the allowed set. A prebuilt `require_admin = require_roles(UserRole.admin)` is provided.

These dependencies are attached globally to routers via `app.include_router(..., dependencies=require_auth)` in `main.py`, so every endpoint under those routers inherits the 401/403 behavior without per-endpoint checks.

### Router-Level Errors

Routers raise domain-specific `HTTPException`s with explicit status codes:

| File | Pattern | Example |
|---|---|---|
| `routers/auth_router.py` | 401 on bad login | `HTTPException(401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})` |
| `routers/daraz_router.py` | 401 missing token, 403 unauthorized connection, 400 invalid encrypted token, 422 upstream API rejection, 502 invalid response shape | `_resolve_daraz_access_token` validates presence, ownership, and decryption; downstream calls map Daraz `code != "0"` responses into 422 payloads carrying `daraz_code`, `daraz_message`, `daraz_details`, `request_id` |
| `routers/shopify_router.py` | 401/403/422 for Shopify OAuth flow errors | Similar structure to Daraz router |
| `routers/reviews_router.py` | 400 for missing reviews, 500 for AI analysis failure | Catches service exceptions and wraps them |
| `routers/customer_support_router.py` | Generic `except Exception as e: raise HTTPException(500, str(e))` | Broad catch-all around MCP client calls |
| `routers/forecast_router.py` | Same broad catch-all pattern |
| `routers/product_listing_router.py` | `raise HTTPException(502, f"Listing generation failed: {exc}") from exc` — preserves chain via `from exc` |
| `routers/storage_router.py` | 409 duplicate connection, 415 unsupported image type |

### WebSocket Error Handling

`dependencies.get_current_user_ws` and `routers/daraz_router.get_daraz_access_token_ws` both convert `HTTPException` into `WebSocketException(code=WS_1008_POLICY_VIOLATION, reason=...)`. This is the only place where HTTP errors are bridged to the WebSocket protocol.

### Utility Exceptions

`utils/security.py` raises a bare `RuntimeError("SECRET_KEY is not configured")` if encryption keys are missing during Fernet initialization. This is an internal invariant check rather than a user-facing error.

## Architecture & Conventions Observed

1. **No custom exception classes** — all business and transport errors are expressed as `fastapi.HTTPException` (or `WebSocketException`).
2. **Auth errors are centralized** in `dependencies.py`; routers never construct their own 401/403 credential exceptions — they reuse the shared `credentials_exception` variable.
3. **External API failures are mapped to specific HTTP codes**: upstream validation problems become 422, malformed upstream responses become 502, client input problems become 400/403/409/415.
4. **Upstream error context is preserved**: Daraz/Shopify failures include nested dicts with `daraz_code`, `daraz_message`, `daraz_details`, `request_id` so callers can surface diagnostic data.
5. **Broad `except Exception` catch blocks** appear in a few routers (`customer_support_router`, `forecast_router`) that wrap MCP/LLM calls; these swallow the original traceback and return a flat 500 string — inconsistent with the more structured mapping elsewhere.
6. **No global exception handler** is registered in `main.py`; FastAPI's default exception handling is relied upon.
7. **CORS middleware** is the only cross-cutting middleware added; there is no logging, tracing, or error-reporting middleware.
8. **Pydantic model validators** raise plain `ValueError` (e.g., `MigrateImageRequest.require_source`) and let FastAPI translate them into 422 validation errors.

## Constraints & Rules

- Authentication failures must go through `get_current_user` / `get_current_user_ws` so that the correct `WWW-Authenticate` header or WebSocket close code is emitted — ad-hoc 401s in routers bypass this convention.
- Role checks should use `require_roles(...)` rather than manual `if current_user.role not in roles` branches, keeping the 403 message uniform.
- When wrapping third-party SDK errors (Daraz, Shopify), preserve the original exception via `from exc` (seen in `product_listing_router.py`) so tracebacks remain debuggable.
- External API responses are validated before being returned; any deviation from the expected shape triggers an `HTTPException` rather than propagating raw upstream objects.