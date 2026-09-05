---
kind: logging_system
name: Standard Library Logging with Per-Module Loggers and No Central Configuration
category: logging_system
scope:
    - '**'
source_files:
    - neurocom_backend/main.py
    - neurocom_backend/routers/daraz_router.py
    - neurocom_backend/routers/tijarah_chat_router.py
    - neurocom_backend/routers/whatsapp_support_router.py
    - neurocom_backend/services/daraz_service.py
    - neurocom_backend/services/daraz_catalog_service.py
    - neurocom_backend/services/storage_service.py
    - neurocom_backend/services/tijarah_chat_service.py
    - neurocom_backend/services/whatsapp_agent_service.py
    - neurocom_backend/python/lazop/base.py
---

## What system/approach is used

The application uses Python's built-in `logging` module exclusively — no third-party logging frameworks (loguru, structlog, etc.) are imported anywhere in the codebase. Each module that needs to log creates its own logger via `logging.getLogger(__name__)`, which is the standard per-module pattern. There is no centralized logging configuration file, no `logging.basicConfig()` call at application startup, and no structured-log library.

The only place where a concrete handler/formatter/sink is configured is inside the vendored `neurocom_backend/python/lazop/base.py` SDK: it sets up a `FileHandler` writing to `~/logs/lazopsdk.log.<YYYY-MM-DD>` with an ERROR-level threshold and a simple `%(message)s` formatter. This is isolated to that SDK and does not affect the rest of the application.

Uvicorn/FastAPI logging is left to their defaults; the app does not configure or override them.

## Key files and packages

- `neurocom_backend/main.py` — Application entrypoint; contains a single inline `logging.getLogger(__name__).warning(...)` call when the WhatsApp scheduler fails to start during lifespan setup.
- `neurocom_backend/routers/daraz_router.py` — Defines `logger = logging.getLogger(__name__)` at module scope and logs warnings for rejected Daraz API responses (e.g., category attributes, product creation), including contextual fields like `category_id`, `code`, `request_id`, and the full diagnostic payload serialized via `json.dumps`.
- `neurocom_backend/routers/tijarah_chat_router.py`, `whatsapp_support_router.py` — Same per-module logger pattern.
- `neurocom_backend/services/daraz_service.py`, `daraz_catalog_service.py`, `storage_service.py`, `tijarah_chat_service.py`, `whatsapp_agent_service.py` — All follow the same `import logging` + `logger = logging.getLogger(__name__)` pattern.
- `neurocom_backend/python/lazop/base.py` — The only file that configures a real sink: a daily-rotating `FileHandler` under `~/logs/` at ERROR level, plus constants `P_LOG_LEVEL_DEBUG/INFO/ERROR` and a `log_level` class attribute on `LazopClient` that gates debug/info output.

## Architecture and conventions

1. **Per-module logger**: Every module that logs declares `logger = logging.getLogger(__name__)` at import time. This produces a logger named after the module (e.g., `neurocom_backend.routers.daraz_router`), enabling hierarchical filtering if a root handler were ever attached.
2. **No global configuration**: There is no `logging.config.dictConfig`, no `basicConfig`, and no shared `utils/logging.py`. Each module relies on whatever handlers the root logger has installed (in practice, none beyond uvicorn's default).
3. **Log levels used descriptively**:
   - `logger.warning(...)` is used for recoverable business errors such as external API rejections (Daraz returning non-zero codes).
   - `logging.getLogger(__name__).warning(...)` is used for startup failures (WhatsApp scheduler).
   - The vendored Lazop SDK uses `logger.error(...)` for HTTP/API errors and exposes a `log_level` attribute to toggle DEBUG/INFO/ERROR output.
4. **Structured-ish messages**: Instead of using dict payloads or a structured-logging framework, modules format context into the message string using positional arguments to `logger.warning(...)` (e.g., `"Daraz category attributes rejected: category_id=%s response=%s"`). The `response` field is serialized with `json.dumps(response, default=str)` so nested objects appear as JSON strings in the log line.
5. **External SDK isolation**: The Lazop SDK (`python/lazop/base.py`) writes to a separate file (`~/logs/lazopsdk.log.<date>`) independent from any application log stream, because it configures its own logger with its own handler.

## Conventions and constraints

- **Convention observed**: Every logging-capable module imports `logging` and creates a module-scoped `logger = logging.getLogger(__name__)`; this is consistent across routers and services.
- **Constraint enforced by the Lazop SDK**: Error output from the Lazop client is always written to `~/logs/lazopsdk.log.<YYYY-MM-DD>` via a dedicated `FileHandler` set to ERROR level; this cannot be changed without modifying the SDK source.
- **No enforced application-wide log level**: Because there is no central configuration, the effective log level depends entirely on what uvicorn installs by default and whether a handler is attached elsewhere. The application itself does not enforce a minimum level.
- **No structured-log schema**: There is no documented log record schema (no fixed set of fields, no correlation IDs injected automatically). Contextual data is embedded ad-hoc in the message string.
- **Error handling vs logging**: Business errors from downstream APIs (e.g., Daraz) are logged at `WARNING` *and* raised as `HTTPException`s with rich detail bodies; informational flow continues without logging every successful call.