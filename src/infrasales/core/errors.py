"""The error middleware: unexpected errors become safe responses, logged under the request ID.

It is the innermost middleware, so its responses get the security and caching headers like
any other. A database that is down, overloaded or timing out answers 503 with `Retry-After`:
clients and load balancers retry instead of treating it as a bug.
"""

from collections.abc import Sequence
from typing import cast

import structlog
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_log = structlog.stdlib.get_logger(__name__)
_UNAVAILABLE = (OperationalError, PoolTimeoutError)
RETRY_AFTER_SECONDS = 5


class ErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        responded = False

        async def tracked_send(message: Message) -> None:
            nonlocal responded
            responded = responded or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as error:  # last resort: log it, never leak it
            unavailable = isinstance(error, _UNAVAILABLE)
            _log.exception("database_unavailable" if unavailable else "unhandled_error")
            if responded:
                raise  # too late for a clean answer: the server aborts the response
            await _response(scope, unavailable=unavailable)(scope, receive, tracked_send)


def _response(scope: Scope, *, unavailable: bool) -> JSONResponse:
    """Only the request ID (set by `RequestContextMiddleware`), never details."""
    request_id = scope.get("state", {}).get("request_id")
    if unavailable:
        return JSONResponse(
            {"detail": "Service Unavailable", "request_id": request_id},
            status_code=503,
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )
    return JSONResponse({"detail": "Internal Server Error", "request_id": request_id}, 500)


async def invalid_request(_: Request, error: Exception) -> JSONResponse:
    """422 with what was wrong, never the input that was: it may be a secret."""
    errors = error.errors() if isinstance(error, RequestValidationError) else ()
    detail = [_without_input(each) for each in cast("Sequence[dict[str, object]]", errors)]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


def _without_input(error: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in error.items() if key != "input"}
