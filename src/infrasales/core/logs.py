"""Structured logging."""

import logging
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Literal, TextIO, cast

import structlog
from opentelemetry import trace
from structlog.tracebacks import ExceptionDictTransformer
from structlog.types import EventDict, Processor, WrappedLogger

type LogFormat = Literal["json", "console"]

_MASK = "[redacted]"
_DETAIL = re.compile(r"^DETAIL:.*$", re.MULTILINE)
_SENSITIVE = ("authorization", "cookie", "password", "secret", "token", "api_key", "database_url")


def _sensitive(key: object) -> bool:
    return any(marker in str(key).lower() for marker in _SENSITIVE)


def _scrub(value: object) -> object:
    """Mask values under sensitive keys, at any depth (e.g. audit before/after payloads)."""
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {key: _MASK if _sensitive(key) else _scrub(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in cast("Iterable[object]", value)]
    return value


def _redact(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    return {key: _MASK if _sensitive(key) else _scrub(value) for key, value in event.items()}


def _trace_context(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    """Tag log lines with the current trace, so logs and traces join up."""
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        event["trace_id"] = format(span.trace_id, "032x")
        event["span_id"] = format(span.span_id, "016x")
    return event


def _drop_database_details(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    """Drop PostgreSQL's DETAIL lines from logged exceptions: they repeat row values."""
    for exception in event.get("exception", ()):
        exception["exc_value"] = _DETAIL.sub("DETAIL: [redacted]", exception["exc_value"])
    return event


def configure_logging(
    *, log_format: LogFormat = "json", level: str = "INFO", stream: TextIO | None = None
) -> None:
    """Route structlog and stdlib loggers (uvicorn, SQLAlchemy, ...) through one formatter."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # request_id
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),  # log.info("%s scraped", item)
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _trace_context,
        _redact,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    # Tracebacks without local variables: frames hold session tokens, passwords and claims.
    output: list[Processor] = (
        [
            structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)),
            _drop_database_details,
            structlog.processors.JSONRenderer(),
        ]
        if log_format == "json"
        else [structlog.dev.ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback)]
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *output],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # replaced by the request log line
    for name in ("httpx", "httpx2", "httpcore", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)  # request lines carry full URLs


def add_handler(handler: logging.Handler) -> None:
    """Send every log record to `handler` too (e.g. OTLP), formatted as on stdout."""
    root = logging.getLogger()
    handler.setFormatter(root.handlers[0].formatter)
    root.addHandler(handler)


def remove_handler(handler: logging.Handler) -> None:
    """Stop sending log records to `handler`; a handler never added is no error."""
    logging.getLogger().removeHandler(handler)
