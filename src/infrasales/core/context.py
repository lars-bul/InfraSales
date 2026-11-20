"""Per request: a server-generated ID and one access log line."""

import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_log = structlog.stdlib.get_logger(__name__)


class RequestContextMiddleware:
    """Bind a request ID to every log line, return it as `X-Request-ID`, log the request once.

    The outermost middleware: every response is logged, also those other middleware answer. The
    ID is in the request state too (`request.state.request_id`), for error responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status, started = 500, time.perf_counter()  # 500 unless a response starts

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
