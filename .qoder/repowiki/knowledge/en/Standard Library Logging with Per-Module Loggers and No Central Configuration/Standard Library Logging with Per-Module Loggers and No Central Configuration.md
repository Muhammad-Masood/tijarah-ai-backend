---
kind: logging_system
name: Standard Library Logging with Per-Module Loggers and No Central Configuration
category: logging_system
scope:
    - '**'
source_files:
    - neurocom_backend/routers/daraz_router.py
    - neurocom_backend/services/daraz_service.py
    - neurocom_backend/utils/redis_cache.py
    - neurocom_backend/utils/sse.py
    - neurocom_backend/services/storage_service.py
    - neurocom_backend/python/lazop/base.py
    - neurocom_backend/main.py
---

## What system/approach is used

The application uses Python's built-in `logging` module exclusively — no third-party logging framework (no loguru, structlog, python-json-logger, etc.) is imported anywhere in the project. There is no centralized logger configuration, no root logger setup, no custom formatter or handler installed at application startup, and no structured-log library. The only exception is a vendored SDK (`neurocom_backend/python/lazop/base.py`) that configures its own file-based `logging.FileHandler` writing to `~/logs/lazopsdk.log.<date>`.

## Key files and packages

- `neurocom_backend/routers/daraz_router.py` — creates a per-module logger via `logger = logging.getLogger(__name__)` and emits `logger.warning(...)` for rejected Daraz API responses.
- `neurocom_backend/services/daraz_service.py` — same pattern; uses `logger.info(...)` to emit a structured-style payload summary when creating products and `logger.error(...)` / `logger.warning(...)` on failures.
- `neurocom_backend/utils/redis_cache.py` — per-module logger used to record cache refresh events and background-refresh exceptions.
- `neurocom_backend/utils/sse.py` — per-module logger for SSE-related events.
- `neurocom_backend/services/storage_service.py` — per-module logger.
- `neurocom_backend/python/lazop/base.py` — standalone SDK that installs its own root logger with an `ERROR`-level `FileHandler` writing daily-rotated logs under `~/logs/lazopsdk.log.<YYYY-MM-DD>`; exposes constants `P_LOG_LEVEL_DEBUG`, `P_LOG_LEVEL_INFO`, `P_LOG_LEVEL_ERROR` and a `LazopClient.log_level` attribute to toggle debug/info/error output.

## Architecture and conventions

- **Per-module logger instances**: Every module that logs does `import logging` followed by `logger = logging.getLogger(__name__)`. This gives each logger a dotted name matching its module path (e.g. `neurocom_backend.routers.daraz_router`), which is the standard Python convention and allows downstream consumers to configure handlers per package.
- **No central configuration**: `main.py` (the FastAPI entrypoint) never calls `logging.basicConfig`, `logging.config.dictConfig`, or attaches any handler to the root logger. As a result, unconfigured loggers fall back to Python's default behavior (messages are emitted but typically not visible unless the process is run with `-m uvicorn --log-level ...` or a handler is attached elsewhere).
- **Log levels used**: The codebase uses `logger.info`, `logger.warning`, and `logger.error`. There are no `debug` calls in application code; the only debug-level control lives inside the vendored Lazop SDK via `LazopClient.log_level`.
- **Structured-ish fields via keyword arguments**: Messages are formatted with positional `%s` placeholders carrying named semantic fields (e.g. `code=...`, `request_id=...`, `category_id=...`, `title_length=...`). This is *not* JSON-structured logging — it is plain text with key=value tokens embedded in the message string. Consumers would need to parse the message text to extract fields.
- **External SDK logging is isolated**: The Lazop SDK sets up its own root logger and file handler at import time, independent of the application's logger hierarchy. Its logs go to a separate file and are not routed through the app's log stream.

## Conventions and constraints

- **Every logging-capable module defines its own `logger` variable** via `logging.getLogger(__name__)`; there is no shared logger object imported from a common module.
- **Errors from upstream APIs are logged before raising HTTPException**: In `daraz_router.py` and `daraz_service.py`, when a Daraz API call returns a non-zero error code, the code first emits a `logger.warning` or `logger.error` containing the response code, message, diagnostic, and request ID, then raises an `HTTPException`. This ensures errors are captured even when the exception is handled by FastAPI.
- **Background tasks log via the same logger**: `redis_cache._background_refresh` uses `logger.exception` to capture stack traces when a stale-while-revalidate refresh fails, and `logger.info` when a key is refreshed.
- **No log rotation or sink configuration exists in this repo**: Aside from the vendored SDK's hardcoded `FileHandler`, there is no RotatingFileHandler, syslog handler, stdout/stderr routing, or integration with an external logging pipeline (e.g. ELK, Datadog, CloudWatch). Whether logs appear depends entirely on how Uvicorn/Gunicorn is started and whether a handler has been attached externally.
- **Debug prints remain alongside log statements**: Several functions still use bare `print(...)` (e.g. `get_access_token`, `_fetch_all_products_raw`, `upload_image`, `get_migrated_images`), indicating the logging migration is incomplete and ad-hoc.