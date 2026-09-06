---
kind: error_handling
name: FastAPI HTTPException-based error handling with centralized auth dependencies
category: error_handling
scope:
    - '**'
source_files:
    - neurocom_backend/dependencies.py
    - neurocom_backend/routers/auth_router.py
    - neurocom_backend/services/order_service.py
    - neurocom_backend/utils/security.py
    - neurocom_backend/main.py
    - neurocom_backend/mcp_server/customer_support/main.py
    - neurocom_backend/mcp_server/client.py
---

## Overview

The Tijarah AI backend uses FastAPI's built-in `HTTPException` as the primary mechanism for signaling errors to clients. There is no custom exception hierarchy, no global exception handler registered via `@app.exception_handler`, and no dedicated `errors/` package. Errors are raised inline in routers and services and rely on FastAPI's default JSON error response format.

## Authentication & Authorization Errors

- **Centralized in `neurocom_backend/dependencies.py`**: The `get_current_user` dependency constructs a single `credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})` and reuses it across JWT decode failures (`jwt.PyJWTError`, `ValueError`) and missing merchant lookups. This ensures consistent 401 responses with the `WWW-Authenticate: Bearer` header required by OAuth2.
- A WebSocket counterpart `get_current_user_ws` raises `WebSocketException(code=WS_1008_POLICY_VIOLATION)` instead of `HTTPException` when authorization fails over WebSockets.
- Role checks use `require_roles(*roles)`, which raises `HTTPException(status_code=403, detail="You do not have permission to perform this action")` when a user lacks the required role.
- All routers opt into authentication via `app.include_router(..., dependencies=[Depends(get_current_user)])`, so unauthorized access to protected routes is handled uniformly at the dependency layer.

## Business Logic Errors

- Services raise `HTTPException` directly for domain-level failures. For example, `order_service.update_order_service`, `delete_order_by_id`, and `get_order_by_id` all raise `HTTPException(status_code=404, detail="Order not found")` when a requested order does not exist.
- The auth router raises `HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})` when login credentials are invalid.
- There is no consistent pattern for other business errors (e.g., validation failures, duplicate entries); most services appear to return data without raising exceptions, leaving error signaling inconsistent across modules.

## External / Runtime Errors

- **Lifespan startup**: In `main.py`, the WhatsApp scheduler start is wrapped in `try/except Exception` and logged via `logging.getLogger(__name__).warning("WhatsApp scheduler failed to start", exc_info=True)` rather than failing the app startup — a graceful degradation choice.
- **MCP SSE server** (`mcp_server/customer_support/main.py`): The SSE request handler wraps the MCP session run in `try/except Exception` and prints the error; there is no structured logging or error response.
- **MCP client** (`mcp_server/client.py`): `get_tools` catches `Exception` and returns `None` after printing an error message, treating external tool discovery failures as non-fatal.
- **Security utilities** (`utils/security.py`): `_get_fernet()` raises `RuntimeError("SECRET_KEY is not configured")` if the encryption key is missing — a process-level configuration error that will bubble up during import/use.

## Middleware & Global Handling

- No custom middleware transforms or logs request/response errors.
- No `@app.exception_handler(Exception)` is defined; FastAPI's default exception handler produces standard JSON error responses with `detail` and `status_code` fields.
- CORS middleware is configured but unrelated to error handling.

## Conventions Observed

1. Use `fastapi.HTTPException` with explicit `status_code` and `detail` for all client-facing errors.
2. Authentication failures consistently include `headers={"WWW-Authenticate": "Bearer"}` to comply with OAuth2 expectations.
3. Centralize credential resolution in `dependencies.py` so routers/services never construct their own 401 exceptions.
4. Non-fatal background task failures (scheduler, MCP tools) are caught and logged/printed rather than propagated.
5. Configuration errors (missing `SECRET_KEY`) raise `RuntimeError` at module level.
6. There is no unified error model or standardized error envelope returned to clients beyond FastAPI's default `HTTPException` JSON shape.