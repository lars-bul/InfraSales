"""Traces, metrics and logs over OTLP, LLM traces in Langfuse. Imported only when configured.

One TracerProvider for everything, owned here and passed on explicitly, never registered as
the global one: the OTLP exporter gets every span (HTTP requests, job runs, agent runs, model
calls), and Langfuse attaches its span processor to the same provider: Langfuse's recommended
setup next to an existing OpenTelemetry pipeline. PydanticAI's agents are instrumented with
the same provider through `Agent.instrument_all`, which is process-wide: one `Telemetry` per
process.

Each job run is one trace. With Langfuse, its user, session, name, tags and metadata are
propagated to every span in it (`langfuse.propagate_attributes`), so Langfuse can filter and
aggregate by user and session.
"""

import json
import logging
import threading
import time
from collections.abc import Generator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, override
from urllib.parse import quote

import structlog
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer, set_span_in_context
from pydantic_ai import Agent, InstrumentationSettings

from infrasales.core.logs import remove_handler
from infrasales.core.models import JSONValue

if TYPE_CHECKING:
    from langfuse import Langfuse

_log = structlog.stdlib.get_logger(__name__)

SCOPE = "infrasales"
OBSERVATION_INPUT = "langfuse.observation.input"
OBSERVATION_OUTPUT = "langfuse.observation.output"
FLUSH_SECONDS = 5.0
_PROJECT_LOOKUP_SECONDS = 60.0
_SECONDS = (0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 900, 3600)


@dataclass(frozen=True, slots=True)
class LangfuseOptions:
    public_key: str
    secret_key: str
    base_url: str
    environment: str | None
    release: str


def _langfuse_resource(langfuse: LangfuseOptions) -> dict[str, str]:
    attributes = {"langfuse.release": langfuse.release}
    if langfuse.environment:
        attributes["langfuse.environment"] = langfuse.environment
    return attributes


@dataclass(frozen=True, slots=True)
class _RunSpan:
    """A job run's span, or one of its steps': input and output, if content may be traced."""

    tracer: Tracer
    span: Span
    content: bool

    @contextmanager
    def step(self, name: str, given: JSONValue = None) -> Generator[_RunSpan]:
        """A child of this span, whatever span is current; current inside, so LLM spans nest."""
        traced = self.content and given is not None
        attributes = {OBSERVATION_INPUT: json.dumps(given)} if traced else {}
        parent = set_span_in_context(self.span)
        with self.tracer.start_as_current_span(name, context=parent, attributes=attributes) as span:
            yield _RunSpan(self.tracer, span, self.content)

    def finish(self, result: JSONValue) -> None:
        if self.content:
            self.span.set_attribute(OBSERVATION_OUTPUT, json.dumps(result))


def _ours(span: ReadableSpan) -> bool:
    return span.instrumentation_scope is not None and span.instrumentation_scope.name == SCOPE


class _LogHandler(LoggingHandler):
    """Exports each log line as stdout prints it: the rendered line is the whole entry.

    It keeps the level, the time, the logger and the trace, and nothing else of the record. Its
    fields would bypass what rendering guarantees: structlog attaches its logger object (which
    OpenTelemetry would warn about on every line), other libraries' fields skip redaction, and
    the raw exception repeats PostgreSQL's DETAIL lines, the rows' values. OpenTelemetry's own
    log records stay on stdout: exporting them would re-enter this handler.
    """

    def __init__(self, logger_provider: LoggerProvider) -> None:
        super().__init__(logger_provider=logger_provider)
        self._lines: logging.Formatter | None = None

    @override
    def setFormatter(self, fmt: logging.Formatter | None) -> None:
        """Render each line with `fmt` (stdout's); the export takes the line as it is."""
        self._lines = fmt

    @override
    def emit(self, record: logging.LogRecord) -> None:
        if record.name.partition(".")[0] == "opentelemetry":
            return
        line = self._lines.format(record) if self._lines else record.getMessage()
        fields = {"name": record.name, "levelno": record.levelno, "levelname": record.levelname}
        super().emit(logging.makeLogRecord(fields | {"created": record.created, "msg": line}))


class Telemetry:
    def __init__(
        self, *, otlp: bool, langfuse: LangfuseOptions | None, trace_content: bool
    ) -> None:
        """`otlp`: export to OTEL_EXPORTER_OTLP_ENDPOINT (OTEL_* variables tune it).

        `trace_content`: include prompts, completions and job results in traces.
        """
        self._trace_content = trace_content
        resource = Resource.create()  # OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
        if langfuse:
            resource = resource.merge(Resource(_langfuse_resource(langfuse)))
        self.tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        self._logger_provider: LoggerProvider | None = None
        self._log_handler: _LogHandler | None = None
        readers: list[MetricReader] = []
        if otlp:
            self.tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            self._logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
            self._logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(OTLPLogExporter())
            )
            self._log_handler = _LogHandler(self._logger_provider)
            readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
        self._meter_provider = MeterProvider(
            resource=resource, metric_readers=readers, shutdown_on_exit=False
        )
        self._tracer = self.tracer_provider.get_tracer(SCOPE)
        meter = self._meter_provider.get_meter(SCOPE)
        self._job_attempts = meter.create_counter(
            "infrasales.job.attempts", unit="{attempt}", description="Job attempts by outcome"
        )
        self._job_duration = meter.create_histogram(
            "infrasales.job.duration",
            unit="s",
            description="How long a job attempt ran",
            explicit_bucket_boundaries_advisory=_SECONDS,
        )
        self._queue_depth = meter.create_gauge(
            "infrasales.job.queue_depth",
            unit="{run}",
            description="Runs due and waiting for a worker",
        )
        self._queue_wait = meter.create_gauge(
            "infrasales.job.queue_wait",
            unit="s",
            description="How long the oldest due run has waited",
        )
        self._job_start_delay = meter.create_histogram(
            "infrasales.job.start_delay",
            unit="s",
            description="How long after it was due a job attempt started: backlog, outages",
            explicit_bucket_boundaries_advisory=_SECONDS,
        )
        self._langfuse: Langfuse | None = None
        self._langfuse_url = langfuse.base_url.rstrip("/") if langfuse else ""
        self._project: str | None = None
        self._next_lookup = 0.0
        if langfuse:
            from langfuse import Langfuse, is_default_export_span

            self._langfuse = Langfuse(
                public_key=langfuse.public_key,
                secret_key=langfuse.secret_key,
                base_url=langfuse.base_url,
                environment=langfuse.environment,
                release=langfuse.release,
                tracer_provider=self.tracer_provider,
                should_export_span=lambda span: is_default_export_span(span) or _ours(span),
            )
            self._look_up_project()
        Agent.instrument_all(
            InstrumentationSettings(
                tracer_provider=self.tracer_provider, include_content=trace_content
            )
        )

    def instrument(self, app: FastAPI) -> None:
        """Trace every request except the probes."""
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=self.tracer_provider,
            excluded_urls="healthz,readyz",
            exclude_spans=["receive", "send"],
        )

    @contextmanager
    def trace_job(
        self,
        name: str,
        *,
        session_id: str,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, str],
    ) -> Generator[_RunSpan]:
        """Trace one job run as a trace of its own, named after the job.

        `user.id` and `session.id` (OpenTelemetry semantic conventions) mark the root span for
        any backend; with Langfuse they, the tags and the metadata reach every span in it. The
        run (job, run ID, attempt, scheduled time) is the trace's input; its result, once
        `finish`ed, the output, if content may be traced. Its steps nest inside, as spans.
        """
        run = json.dumps({"job": name, "run_id": session_id, **metadata})
        attributes = {"session.id": session_id, OBSERVATION_INPUT: run}
        attributes |= {"user.id": user_id} if user_id else {}
        with (
            self._tracer.start_as_current_span(f"job {name}", attributes=attributes) as span,
            self._propagate(name, session_id, user_id, tags, metadata),
        ):
            yield _RunSpan(self._tracer, span, self._trace_content)

    def _propagate(  # Langfuse's trace attributes
        self,
        name: str,
        session_id: str,
        user_id: str | None,
        tags: Sequence[str],
        metadata: Mapping[str, str],
    ) -> AbstractContextManager[object]:
        if not self._langfuse:
            return nullcontext()
        from langfuse import propagate_attributes

        return propagate_attributes(
            trace_name=name,
            session_id=session_id,
            user_id=user_id,
            tags=list(tags),
            metadata=dict(metadata),
        )

    def record_queue(self, *, depth: int, wait: float) -> None:
        """Set the queue's gauges: runs due and waiting, the oldest one's wait (s)."""
        self._queue_depth.set(depth)
        self._queue_wait.set(wait)

    def record_job(
        self, name: str, *, outcome: str, duration: float | None, start_delay: float | None
    ) -> None:
        """Measure one finished attempt of the job `name` (exported over OTLP, if on).

        Without a duration and delay (a dead worker's attempt) only its outcome is counted.
        """
        attributes = {"job": name, "outcome": outcome}
        self._job_attempts.add(1, attributes)
        if duration is not None:
            self._job_duration.record(duration, attributes)
        if start_delay is not None:
            self._job_start_delay.record(start_delay, {"job": name})

    def session_url(self, session_id: str) -> str | None:
        """A session's page in Langfuse (a job run with its retries); None until it can be told.

        The URL names the Langfuse project the keys belong to: it is looked up in the
        background, and while it is unknown, again at most once a minute.
        """
        if self._langfuse is None:
            return None
        if self._project is None:
            self._look_up_project()
            return None
        return f"{self._langfuse_url}/project/{self._project}/sessions/{quote(session_id, safe='')}"

    def _look_up_project(self) -> None:
        """Ask Langfuse in a daemon thread: never holding a request, nor the process at exit."""
        if self._langfuse is None or (now := time.monotonic()) < self._next_lookup:
            return
        self._next_lookup = now + _PROJECT_LOOKUP_SECONDS
        lookup = threading.Thread(
            target=self._find_project, args=(self._langfuse,), name="langfuse-project", daemon=True
        )
        lookup.start()

    def _find_project(self, langfuse: Langfuse) -> None:
        try:
            projects = langfuse.api.projects.get().data
        except Exception:  # noqa: BLE001  # unreachable, or the keys are wrong: links wait
            _log.warning("telemetry.langfuse_project_unknown", exc_info=True)
            return
        self._project = next((project.id for project in projects), None)  # keys: one project

    def log_handler(self) -> logging.Handler | None:
        """The handler exporting log records over OTLP, if OTLP is on (`add_handler` adds it)."""
        return self._log_handler

    def shutdown(self, timeout: float = FLUSH_SECONDS) -> None:
        """Flush what is buffered and stop exporting, within `timeout` seconds in all.

        Log records go to stdout only from then on: the server still logs after the app shut
        down, and an exporter that stopped would only report that it ignores them. The SDK waits
        up to 30 s per exporter, one after another: a slow or unreachable backend must not hold
        the process past its grace period. The flush runs in a daemon thread; what is still
        unsent after `timeout` is dropped, and nothing waits for it at exit.
        """
        if self._log_handler:
            remove_handler(self._log_handler)
        Agent.instrument_all(instrument=False)
        flushing = threading.Thread(target=self._flush, name="telemetry-flush", daemon=True)
        flushing.start()
        flushing.join(timeout)
        if flushing.is_alive():
            _log.warning("telemetry.flush_timed_out", seconds=timeout)

    def _flush(self) -> None:
        if self._langfuse:
            self._langfuse.shutdown()
        self.tracer_provider.shutdown()
        self._meter_provider.shutdown()
        if self._logger_provider:
            self._logger_provider.shutdown()
