"""Server-Sent Events helpers shared by streaming endpoints.

Pipeline services expose a `..._stream()` generator that yields
`(event_name, data)` pairs as work completes (see reviews_service and
daraz_service). `sse_stream` adapts one of those into wire-format SSE
frames for `StreamingResponse`. Because `StreamingResponse` runs a plain
(sync) generator via Starlette's `iterate_in_threadpool`, these pipelines
don't need to be rewritten as async to avoid blocking the event loop.
"""

import json
import logging
from typing import Any, Iterable, Iterator, Tuple

logger = logging.getLogger(__name__)


def format_sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def sse_stream(events: Iterable[Tuple[str, Any]]) -> Iterator[str]:
    """Formats each (event, data) pair as it arrives. A mid-stream exception
    can't become an HTTP error status (the 200 + headers are already sent by
    the time a generator yields its first item), so it's turned into a final
    `error` event instead of crashing the connection with no explanation."""
    try:
        for event, data in events:
            yield format_sse(event, data)
    except Exception as exc:
        logger.exception("SSE stream failed mid-pipeline")
        yield format_sse("error", {"detail": str(exc)})
