"""Telemetry for this process, from settings: nothing is imported when it is off."""

from typing import TYPE_CHECKING

from infrasales.core.logs import add_handler
from infrasales.core.state import StateKey
from infrasales.settings import WorkerSettings

if TYPE_CHECKING:
    from infrasales.core.telemetry import Telemetry

TELEMETRY = StateKey["Telemetry"]("telemetry")  # set while the app traces: links to its traces


def start_telemetry(settings: WorkerSettings) -> Telemetry | None:
    """Start exporting traces and logs as configured; None if no exporter is."""
    if not settings.otel_exporter_otlp_endpoint and not settings.langfuse_public_key:
        return None
    from infrasales.core.telemetry import LangfuseOptions, Telemetry

    langfuse = (
        LangfuseOptions(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=str(settings.langfuse_base_url).rstrip("/"),
            environment=settings.langfuse_tracing_environment,
            release=settings.langfuse_release,
        )
        if settings.langfuse_public_key and settings.langfuse_secret_key
        else None
    )
    telemetry = Telemetry(
        otlp=bool(settings.otel_exporter_otlp_endpoint),
        langfuse=langfuse,
        trace_content=settings.llm.trace_content,
    )
    if handler := telemetry.log_handler():
        add_handler(handler)
    return telemetry
