---
kind: error_handling
name: FastAPI HTTPException-based Error Handling with Centralized Auth Dependencies
category: error_handling
scope:
    - '**'
source_files:
    - neurocom_backend/dependencies.py
    - neurocom_backend/routers/auth_router.py
    - neurocom_backend/services/user_service.py
    - neurocom_backend/utils/security.py
    - neurocom_backend/main.py
    - neurocom_backend/mcp_server/client.py
    - neurocom_backend/mcp_server/customer_support/main.py
---

## What system/approach is used

The Tijarah AI backend uses FastAPI's built-in `HTTPException` (and `WebSocketException`) as its primary error signaling mechanism. There is no custom exception hierarchy, no centralized error-response model, and no global exception handler registered in the application. Errors are raised inline at the point of failure — primarily in routers and dependencies — and FastAPI converts them into JSON responses automatically.

Authentication and authorization errors are funneled through reusable dependency functions (`get_current_user`, `get_current_user_ws`, `require_roles`) that construct standardized `HTTPException` / `WebSocketException` instances with consistent status codes and messages. This is the closest thing the codebase has to a shared error contract.

## Key files and packages

- **`neurocom_backend/dependencies.py`** — Central place for auth-related errors. Defines `credentials_exception` (401 Unauthorized) reused across `get_current_user` and `get_current_user_ws`, plus `require_roles` which raises 403 Forbidden when role checks fail. Also defines `require_admin` as a convenience alias.
- **`neurocom_backend/routers/auth_router.py`** — Raises 401 on failed login via `HTTPException(status_code=401_UNAUTHORIZED, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})`.
- **`neurocom_backend/services/user_service.py`** — Raises 400 Bad Request (`detail="Merchant already exists"`) when duplicate merchant signup is attempted.
- **`neurocom_backend/utils/security.py`** — Raises a bare `RuntimeError("SECRET_KEY is not configured")` if encryption keys are missing; this is an internal invariant rather than a client-facing error.
- **`neurocom_backend/main.py`** — No global exception handler is mounted. The only top-level try/except catches startup failures (e.g. WhatsApp scheduler start) and logs them via `logging.warning(..., exc_info=True)` without re-raising.
- **`neurocom_backend/mcp_server/client.py`** and **`mcp_server/customer_support/main.py`** — Wrap external calls in `try/except Exception` blocks and log errors; they do not raise structured exceptions back to callers.

## Architecture and conventions

1. **Routers stay thin.** Routers call service functions and raise `HTTPException` only for user-facing validation/authentication failures (e.g. wrong credentials). Business logic lives in services, which return domain values or `None` (see `authenticate_merchant` returning `None` on bad credentials), letting the router decide how to translate that into an HTTP response.
2. **Auth errors are centralized.** All unauthorized/forbidden cases go through `dependencies.py`. `get_current_user` builds a single `credentials_exception` instance and reuses it everywhere JWT decoding fails, the subject is missing, the account type is not `merchant`, or the merchant row is not found. Role enforcement goes through `require_roles`, which raises 403 with a fixed message.
3. **WebSocket auth mirrors HTTP auth.** `get_current_user_ws` reads the `Authorization` header directly from the WebSocket handshake (bypassing `OAuth2PasswordBearer`, which requires an HTTP request) and raises `WebSocketException(code=WS_1008_POLICY_VIOLATION, reason="Could not validate credentials")` on failure.
4. **No global error handler.** The app does not register a `@app.exception_handler` for `HTTPException` or any other exception type. FastAPI's default behavior produces a JSON body like `{"detail": "..."}` with the appropriate status code.
5. **Startup errors are logged, not propagated.** In the lifespan, `start_scheduler()` is wrapped in `try/except Exception` and logged with `exc_info=True`; the server continues running even if the scheduler fails.
6. **External calls swallow exceptions.** MCP client and customer support SSE code catch `Exception` broadly and log it rather than propagating structured errors upward.

## Conventions and constraints

- **Unauthorized access** → `HTTPException(status_code=401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})` from `get_current_user` / `get_current_user_ws`, or `HTTPException(status_code=401_UNAUTHORIZED, detail="Incorrect email or password", ...)` from the login endpoint.
- **Forbidden access** → `HTTPException(status_code=403_FORBIDDEN, detail="You do not have permission to perform this action")` from `require_roles`.
- **Duplicate resource creation** → `HTTPException(status_code=400, detail="Merchant already exists")` from `store_new_user`.
- **Configuration errors** → Bare `RuntimeError` raised inside `_get_fernet` when `SECRET_KEY` is unset; this is an internal crash path, not a client error.
- **Role enforcement pattern**: `require_roles(*roles: UserRole)` returns a dependency that wraps `get_current_user` and rejects users whose `role` is not in the allowed set.
- **No custom exception classes exist** anywhere in the codebase; all errors are expressed as FastAPI exceptions or raw Python exceptions.
- **No middleware transforms errors**; only `CORSMiddleware` is mounted.