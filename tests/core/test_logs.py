import io
import json
import logging

import structlog
from opentelemetry.sdk.trace import TracerProvider

from infrasales.core.logs import add_handler, configure_logging


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_structlog_and_stdlib_loggers_write_json_lines() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    structlog.stdlib.get_logger("infrasales.test").info("%s scraped", "Hello", source="example")
    logging.getLogger("library").warning("plain %s", "message")

    app, library = _lines(stream)
    assert app["event"] == "Hello scraped"
    assert app["source"] == "example"
    assert app["level"] == "info"
    assert app["logger"] == "infrasales.test"
    assert str(app["timestamp"]).endswith("Z")
    assert library["event"] == "plain message"
    assert library["level"] == "warning"


def test_sensitive_values_are_masked_at_any_depth() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    structlog.stdlib.get_logger().info(
        "event", api_key="k", payload={"password": "p", "rows": [{"token": "t"}], "kept": 1}
    )

    (line,) = _lines(stream)
    assert line["api_key"] == "[redacted]"
    assert line["payload"] == {
        "password": "[redacted]",
        "rows": [{"token": "[redacted]"}],
        "kept": 1,
    }


def _insert(secret: str) -> None:
    message = f"duplicate key ({len(secret)})\nDETAIL:  Key (email)=(a@b.c) already exists."
    raise ValueError(message)


def test_exceptions_are_rendered_without_locals_or_database_details() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    try:
        _insert("local-value")
    except ValueError:
        structlog.stdlib.get_logger().exception("failed")

    (line,) = _lines(stream)
    assert "local-value" not in stream.getvalue()
    assert "a@b.c" not in stream.getvalue()
    assert "DETAIL: [redacted]" in json.dumps(line["exception"])


def test_console_format_and_level() -> None:
    stream = io.StringIO()
    configure_logging(log_format="console", level="warning", stream=stream)

    structlog.stdlib.get_logger().info("hidden")
    structlog.stdlib.get_logger().warning("shown")

    assert "hidden" not in stream.getvalue()
    assert "shown" in stream.getvalue()


def test_lines_logged_inside_a_span_carry_its_trace() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("work") as span:
        structlog.stdlib.get_logger().info("inside")
    structlog.stdlib.get_logger().info("outside")

    inside, outside = _lines(stream)
    assert inside["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert "span_id" in inside
    assert "trace_id" not in outside


def test_added_handlers_get_the_same_format() -> None:
    stream, extra = io.StringIO(), io.StringIO()
    configure_logging(stream=stream)

    add_handler(logging.StreamHandler(extra))
    structlog.stdlib.get_logger().info("twice")

    assert stream.getvalue() == extra.getvalue()


def test_uvicorn_logs_propagate_and_its_access_log_is_off() -> None:
    logging.getLogger("uvicorn").addHandler(logging.NullHandler())
    configure_logging(stream=io.StringIO())

    assert logging.getLogger("uvicorn").handlers == []
    assert logging.getLogger("uvicorn").propagate
    assert logging.getLogger("uvicorn.access").disabled


def test_http_client_request_lines_are_not_logged() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    logging.getLogger("httpx2").info("HTTP Request: GET https://api.example/?token=t")

    assert stream.getvalue() == ""
