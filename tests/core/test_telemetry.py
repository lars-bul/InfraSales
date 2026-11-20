import io
import json
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from types import SimpleNamespace
from typing import Self, override

import httpx2
import pytest
import structlog
from fastapi import FastAPI
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    Metric,
    NumberDataPoint,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from infrasales.core import telemetry
from infrasales.core.logs import add_handler, configure_logging
from infrasales.core.telemetry import (
    OBSERVATION_INPUT,
    OBSERVATION_OUTPUT,
    LangfuseOptions,
    Telemetry,
)

OPTIONS = LangfuseOptions(
    public_key="pk-lf-test",
    secret_key="sk-lf-test",
    base_url="http://127.0.0.1:9",  # never reached: the tests replace Langfuse's exporter
    environment="development",
    release="1.2.3",
)
RUN = {
    "session_id": "01a0fb79-run",
    "user_id": "basic:alice",
    "tags": ["report", "manual"],
    "metadata": {"attempt": "1"},
}


@dataclass
class Exported:
    spans: InMemorySpanExporter = field(default_factory=InMemorySpanExporter)
    logs: InMemoryLogRecordExporter = field(default_factory=InMemoryLogRecordExporter)
    metrics: InMemoryMetricReader = field(default_factory=InMemoryMetricReader)

    def span_names(self) -> list[str]:
        return [span.name for span in self.spans.get_finished_spans()]


@pytest.fixture(autouse=True)
def exported(monkeypatch: pytest.MonkeyPatch) -> Iterator[Exported]:
    """OTLP exporters that keep what they get, instead of sending it."""
    kept = Exported()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: kept.spans)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda: kept.logs)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda: None)

    def reader(_: object) -> InMemoryMetricReader:  # read by the tests instead of exported
        return kept.metrics

    monkeypatch.setattr(telemetry, "PeriodicExportingMetricReader", reader)
    yield kept
    Agent.instrument_all(instrument=False)


@pytest.mark.anyio
@pytest.mark.parametrize("trace_content", [False, True])
async def test_agent_runs_are_traced_with_content_only_when_asked(
    exported: Exported, *, trace_content: bool
) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=trace_content)

    await Agent(TestModel(custom_output_text="Hello world"), output_type=str).run("a secret")
    pipeline.tracer_provider.force_flush()

    spans = exported.spans.get_finished_spans()
    assert any(name.startswith("invoke_agent") for name in exported.span_names())
    attributes = str([dict(span.attributes or {}) for span in spans])
    assert ("a secret" in attributes) is trace_content
    pipeline.shutdown()


@pytest.mark.anyio
async def test_requests_are_traced_except_the_probes(exported: Exported) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> None:
        pass

    @app.get("/api/items")
    async def items() -> None:
        pass

    pipeline.instrument(app)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/healthz")
        await client.get("/api/items")
    pipeline.tracer_provider.force_flush()

    assert exported.span_names() == ["GET /api/items"]
    pipeline.shutdown()


def _metrics(reader: InMemoryMetricReader) -> dict[str, Metric]:
    data = reader.get_metrics_data()
    assert data
    return {
        metric.name: metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


def test_job_attempts_are_measured_over_otlp(exported: Exported) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)

    pipeline.record_job("report", outcome="succeeded", duration=2.5, start_delay=1.0)
    pipeline.record_job("report", outcome="retrying", duration=0.5, start_delay=0.0)
    pipeline.record_job("report", outcome="failed", duration=None, start_delay=None)  # reaped

    metrics = _metrics(exported.metrics)
    pipeline.shutdown()
    attempts = {
        str(point.attributes and point.attributes["outcome"]): point.value
        for point in metrics["infrasales.job.attempts"].data.data_points
        if isinstance(point, NumberDataPoint)
    }
    assert attempts == {"succeeded": 1, "retrying": 1, "failed": 1}
    (delays,) = metrics["infrasales.job.start_delay"].data.data_points
    assert isinstance(delays, HistogramDataPoint)
    assert (delays.count, delays.sum, delays.attributes) == (2, 1.0, {"job": "report"})
    assert {
        metrics[name].unit for name in ("infrasales.job.duration", "infrasales.job.start_delay")
    } == {"s"}


def test_the_queue_is_measured_over_otlp(exported: Exported) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)

    pipeline.record_queue(depth=3, wait=42.5)

    metrics = _metrics(exported.metrics)
    pipeline.shutdown()
    values = {
        name: [p.value for p in metrics[name].data.data_points if isinstance(p, NumberDataPoint)]
        for name in ("infrasales.job.queue_depth", "infrasales.job.queue_wait")
    }
    assert values == {"infrasales.job.queue_depth": [3], "infrasales.job.queue_wait": [42.5]}


def test_log_records_are_exported_over_otlp(exported: Exported) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)
    handler = pipeline.log_handler()
    assert handler
    logger = logging.getLogger("infrasales.test.telemetry")
    logger.addHandler(handler)

    logger.warning("exported")
    logger.removeHandler(handler)

    assert pipeline.log_handler() is handler  # one per pipeline: `shutdown` detaches it
    pipeline.shutdown()  # flushes
    assert [record.log_record.body for record in exported.logs.get_finished_logs()] == ["exported"]


def _logging_to(stream: io.StringIO) -> Telemetry:
    """Log lines on `stream`, each exported over OTLP as well, as `start_telemetry` sets up."""
    configure_logging(stream=stream)  # the root logger is restored after the test
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)
    handler = pipeline.log_handler()
    assert handler
    add_handler(handler)
    return pipeline


def test_an_exported_log_entry_is_the_line_stdout_prints_and_nothing_else(
    exported: Exported,
) -> None:
    """The same redaction, and no fields of the record: structlog's logger object is one."""
    stream = io.StringIO()
    pipeline = _logging_to(stream)

    structlog.stdlib.get_logger("infrasales.test").info("signed in", password="hunter2")
    pipeline.shutdown()  # flushes

    (entry,) = [record.log_record for record in exported.logs.get_finished_logs()]
    assert entry.body == stream.getvalue().strip()
    assert "hunter2" not in str(entry.body)
    assert not entry.attributes  # no `_logger` (OpenTelemetry warned about it each time)


def _insert() -> None:
    message = "duplicate key\nDETAIL:  Key (email)=(alice@uni.test) already exists."
    raise ValueError(message)


def test_an_exception_is_exported_as_rendered_without_database_details(
    exported: Exported,
) -> None:
    """The record's raw exception would repeat PostgreSQL's DETAIL line: the row's values."""
    stream = io.StringIO()
    pipeline = _logging_to(stream)

    try:
        _insert()
    except ValueError:
        structlog.stdlib.get_logger("infrasales.test").exception("insert failed")
    pipeline.shutdown()

    (entry,) = [record.log_record for record in exported.logs.get_finished_logs()]
    assert "DETAIL: [redacted]" in str(entry.body)
    assert "alice@uni.test" not in str(entry.body) + str(dict(entry.attributes or {}))


def test_opentelemetrys_own_log_records_stay_on_stdout(exported: Exported) -> None:
    """Exported, they would re-enter the handler: OpenTelemetry logs while it exports."""
    stream = io.StringIO()
    pipeline = _logging_to(stream)

    logging.getLogger("opentelemetry.attributes").warning("Invalid type for attribute value")
    pipeline.shutdown()

    assert not exported.logs.get_finished_logs()
    assert "Invalid type for attribute value" in stream.getvalue()


def test_after_shutdown_log_records_go_to_stdout_only(exported: Exported) -> None:
    """Uvicorn logs once more after the app's shutdown: not into a stopped exporter."""
    stream = io.StringIO()
    pipeline = _logging_to(stream)

    pipeline.shutdown()
    logging.getLogger("uvicorn.error").info("Application shutdown complete.")

    assert len(logging.getLogger().handlers) == 1  # stdout's
    assert "Application shutdown complete." in stream.getvalue()
    assert "Shutdown called" not in stream.getvalue()
    assert not exported.logs.get_finished_logs()


def test_langfuse_attaches_to_the_shared_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    def langfuse(**arguments: object) -> None:
        created.append(arguments)

    monkeypatch.setattr("langfuse.Langfuse", langfuse)

    pipeline = Telemetry(otlp=False, langfuse=OPTIONS, trace_content=False)

    (arguments,) = created
    assert arguments["tracer_provider"] is pipeline.tracer_provider  # not a global of its own
    assert (arguments["environment"], arguments["release"]) == ("development", "1.2.3")
    assert arguments["public_key"] == "pk-lf-test"
    assert pipeline.log_handler() is None  # OTLP is off: no log export
    pipeline.shutdown()


class FakeLangfuse:
    """Langfuse's client as far as links go: its projects API, answering or failing."""

    def __init__(self, project: str | None) -> None:
        self.project, self.lookups = project, 0
        self.api = SimpleNamespace(projects=SimpleNamespace(get=self._projects))

    def _projects(self) -> SimpleNamespace:
        self.lookups += 1
        if self.project is None:
            raise ConnectionError  # unreachable, or the keys are wrong
        return SimpleNamespace(data=[SimpleNamespace(id=self.project)])

    def client(self, **_: object) -> Self:  # stands in for `langfuse.Langfuse(...)`
        return self

    def shutdown(self) -> None:
        pass


def _session_url(pipeline: Telemetry, session_id: str) -> str | None:
    """The session's URL once the background lookup had its chance."""
    deadline = time.monotonic() + 5
    while (url := pipeline.session_url(session_id)) is None and time.monotonic() < deadline:
        time.sleep(0.01)
    return url


def test_a_session_links_to_its_page_in_the_keys_langfuse_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("langfuse.Langfuse", FakeLangfuse("project-1").client)
    options = replace(OPTIONS, base_url="https://langfuse.test/")
    pipeline = Telemetry(otlp=False, langfuse=options, trace_content=False)

    url = _session_url(pipeline, "01a0fb79-run")

    assert url == "https://langfuse.test/project/project-1/sessions/01a0fb79-run"
    assert Telemetry(otlp=True, langfuse=None, trace_content=False).session_url("x") is None
    pipeline.shutdown()


@pytest.mark.parametrize(("interval", "lookups"), [(60.0, 1), (0.0, 2)])
def test_an_unknown_project_is_looked_up_again_after_a_while(
    monkeypatch: pytest.MonkeyPatch, interval: float, lookups: int
) -> None:
    """Without a project, no links: asked again at most once a minute (here: `interval`)."""
    stream, langfuse = io.StringIO(), FakeLangfuse(None)
    configure_logging(stream=stream)
    monkeypatch.setattr("langfuse.Langfuse", langfuse.client)
    monkeypatch.setattr(telemetry, "_PROJECT_LOOKUP_SECONDS", interval)
    pipeline = Telemetry(otlp=False, langfuse=OPTIONS, trace_content=False)  # looks it up
    _wait_for(lambda: langfuse.lookups == 1)

    assert pipeline.session_url("01a0fb79-run") is None  # asks again, if it is time
    _wait_for(lambda: langfuse.lookups == lookups)

    assert langfuse.lookups == lookups
    assert "telemetry.langfuse_project_unknown" in stream.getvalue()
    pipeline.shutdown()


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


async def _run_job(pipeline: Telemetry) -> None:
    """What the report does inside its trace: steps, an agent run and a plain span."""
    with pipeline.trace_job("report", **RUN) as trace:  # pyright: ignore[reportArgumentType]
        with trace.step("write") as write:
            with write.step("scrape", ["Hello", "world"]) as scrape:
                scrape.finish(["Hello", "world"])
            await Agent(TestModel(), name="report", output_type=str).run("Hello\nworld")
            write.finish("Hello world")
        with trace.step("mail") as mail, write.step("late"):  # a step's parent: its trace
            mail.finish({"sent": 2})
        with pipeline.tracer_provider.get_tracer("sqlalchemy").start_as_current_span("SELECT"):
            pass
        trace.finish("Hello world")  # the job's result


def _trace_id(span: ReadableSpan) -> int:
    context = span.get_span_context()
    assert context
    return context.trace_id


@pytest.mark.anyio
async def test_a_job_run_is_one_trace_with_its_user_and_session(exported: Exported) -> None:
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)

    await _run_job(pipeline)
    pipeline.tracer_provider.force_flush()

    spans = {span.name: span for span in exported.spans.get_finished_spans()}
    root = spans["job report"]
    assert root.parent is None
    assert dict(root.attributes or {}) == {
        "session.id": "01a0fb79-run",
        "user.id": "basic:alice",
        OBSERVATION_INPUT: '{"job": "report", "run_id": "01a0fb79-run", "attempt": "1"}',
    }  # no output: content is not traced
    assert {_trace_id(span) for span in spans.values()} == {_trace_id(root)}  # one trace
    assert _parents(spans) == {
        "write": "job report",
        "scrape": "write",
        "invoke_agent report": "write",  # the agent runs within the step
        "mail": "job report",
        "late": "write",
        "SELECT": "job report",
    }
    assert not {OBSERVATION_INPUT, OBSERVATION_OUTPUT} & set(_attributes(spans["scrape"]))
    pipeline.shutdown()


def _parents(spans: dict[str, ReadableSpan]) -> dict[str, str]:
    """Each span's parent, by name; the agent's own spans (chat, tools) left out."""
    names = {span.context.span_id: name for name, span in spans.items() if span.context}
    return {
        name: names[span.parent.span_id]
        for name, span in spans.items()
        if span.parent and names[span.parent.span_id] != "invoke_agent report"
    }


def _attributes(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


@pytest.mark.anyio
async def test_langfuse_gets_job_traces_with_user_session_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import langfuse  # noqa: PLC0415  # the real client, with an exporter that keeps spans

    sent_to_langfuse = InMemorySpanExporter()
    keeping = partial(langfuse.Langfuse, span_exporter=sent_to_langfuse)
    monkeypatch.setattr(langfuse, "Langfuse", keeping)
    pipeline = Telemetry(otlp=False, langfuse=OPTIONS, trace_content=False)

    await _run_job(pipeline)
    pipeline.tracer_provider.force_flush()

    spans = sent_to_langfuse.get_finished_spans()
    names = [span.name for span in spans]
    assert "job report" in names
    assert any(name.startswith("invoke_agent report") for name in names)
    assert {"write", "scrape", "mail"} <= set(names)  # the job's steps
    assert "SELECT" not in names  # only LLM spans and our job spans reach Langfuse
    for span in spans:  # every observation carries the trace's identity
        attributes = _attributes(span)
        assert attributes["user.id"] == "basic:alice"
        assert attributes["session.id"] == "01a0fb79-run"
        assert attributes["langfuse.trace.name"] == "report"
        assert list(attributes["langfuse.trace.tags"]) == ["report", "manual"]  # pyright: ignore[reportArgumentType]
        assert span.resource.attributes["langfuse.environment"] == "development"
        assert span.resource.attributes["langfuse.release"] == "1.2.3"
    pipeline.shutdown()


@pytest.mark.anyio
async def test_with_content_traced_langfuse_shows_each_runs_input_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job's span is the trace's root: Langfuse shows its input and output as the trace's."""
    import langfuse  # noqa: PLC0415  # the real client, with an exporter that keeps spans

    sent_to_langfuse = InMemorySpanExporter()
    keeping = partial(langfuse.Langfuse, span_exporter=sent_to_langfuse)
    monkeypatch.setattr(langfuse, "Langfuse", keeping)
    options = replace(OPTIONS, public_key="pk-lf-content")  # Langfuse keeps a client per key
    pipeline = Telemetry(otlp=False, langfuse=options, trace_content=True)

    await _run_job(pipeline)
    pipeline.tracer_provider.force_flush()

    spans = {span.name: _attributes(span) for span in sent_to_langfuse.get_finished_spans()}
    root = spans["job report"]
    assert json.loads(str(root[OBSERVATION_INPUT]))["run_id"] == "01a0fb79-run"
    assert json.loads(str(root[OBSERVATION_OUTPUT])) == "Hello world"  # the job's result
    scrape, mail = spans["scrape"], spans["mail"]
    assert json.loads(str(scrape[OBSERVATION_INPUT])) == ["Hello", "world"]  # each step's
    assert json.loads(str(scrape[OBSERVATION_OUTPUT])) == ["Hello", "world"]
    assert (OBSERVATION_INPUT in mail, json.loads(str(mail[OBSERVATION_OUTPUT]))) == (
        False,  # given nothing
        {"sent": 2},
    )
    agent = next(attrs for name, attrs in spans.items() if name.startswith("invoke_agent"))
    assert "final_result" in agent  # the agent's output, which Langfuse maps
    assert (OBSERVATION_INPUT, OBSERVATION_OUTPUT) == (
        langfuse.LangfuseOtelSpanAttributes.OBSERVATION_INPUT,
        langfuse.LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT,
    )
    pipeline.shutdown()


class Unanswered(InMemorySpanExporter):
    """A backend that never answers: each export waits until the test is done."""

    def __init__(self) -> None:
        super().__init__()
        self.done = threading.Event()

    @override
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.done.wait()
        return super().export(spans)


def test_an_unanswering_backend_holds_the_shutdown_no_longer_than_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream, backend = io.StringIO(), Unanswered()
    configure_logging(stream=stream)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: backend)
    pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)
    with pipeline.tracer_provider.get_tracer("infrasales").start_as_current_span("job"):
        pass

    started = time.monotonic()
    pipeline.shutdown(timeout=0.2)
    took = time.monotonic() - started
    backend.done.set()  # the abandoned flush ends on its own, later

    assert 0.2 <= took < 1
    assert "telemetry.flush_timed_out" in stream.getvalue()


# A process exporting to an OTLP endpoint that accepts connections but never answers.
_UNANSWERED = """
import logging, os, socket
endpoint = socket.create_server(("127.0.0.1", 0))
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://127.0.0.1:{endpoint.getsockname()[1]}"
from infrasales.core.telemetry import Telemetry

pipeline = Telemetry(otlp=True, langfuse=None, trace_content=False)
with pipeline.tracer_provider.get_tracer("infrasales").start_as_current_span("job"):
    pipeline.record_queue(depth=1, wait=0.0)
    logger = logging.getLogger("infrasales.exit")
    logger.addHandler(pipeline.log_handler())
    logger.warning("exported")
pipeline.shutdown(timeout=0.5)
"""


def test_an_unanswering_backend_never_holds_the_process_at_exit() -> None:
    """Spans, metrics and logs all wait for it; the process still exits within the budget."""
    command = [sys.executable, "-c", _UNANSWERED]  # our interpreter and script
    started = time.monotonic()

    subprocess.run(command, check=True, timeout=30)

    assert time.monotonic() - started < 10  # the SDK alone waits ~10 s per exporter


def test_without_an_environment_only_the_release_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    def langfuse(**_: object) -> None:
        pass

    monkeypatch.setattr("langfuse.Langfuse", langfuse)

    options = replace(OPTIONS, environment=None)
    pipeline = Telemetry(otlp=False, langfuse=options, trace_content=False)

    resource = pipeline.tracer_provider.resource.attributes
    assert resource["langfuse.release"] == "1.2.3"
    assert "langfuse.environment" not in resource
    pipeline.shutdown()
