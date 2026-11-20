# Minimal stub: opentelemetry-instrumentation-fastapi ships no type information.
from typing import Literal

from fastapi import FastAPI
from opentelemetry.trace import TracerProvider

class FastAPIInstrumentor:
    @staticmethod
    def instrument_app(
        app: FastAPI,
        *,
        tracer_provider: TracerProvider | None = None,
        excluded_urls: str | None = None,
        exclude_spans: list[Literal["receive", "send"]] | None = None,
    ) -> None: ...
