"""
No-op adapters for all three observability ports.
Used in unit tests and local development where no telemetry backend is running.
Zero external dependencies required.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from ..ports.logger_port import LoggerPort
from ..ports.metrics_port import MetricsPort
from ..ports.tracer_port import SpanPort, TracerPort

# --- No-Op Tracer ---


class NoOpSpan(SpanPort):
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def set_status_error(self, description: str) -> None:
        pass


class NoOpTracer(TracerPort):
    @contextmanager
    def start_span(self, name: str) -> Generator[SpanPort, None, None]:
        yield NoOpSpan()


# --- No-Op Metrics ---


class NoOpMetrics(MetricsPort):
    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        pass

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        pass


# --- No-Op Logger ---


class NoOpLogger(LoggerPort):
    def debug(self, event: str, **kwargs: Any) -> None:
        pass

    def info(self, event: str, **kwargs: Any) -> None:
        pass

    def warning(self, event: str, **kwargs: Any) -> None:
        pass

    def error(self, event: str, **kwargs: Any) -> None:
        pass

    def exception(self, event: str, **kwargs: Any) -> None:
        pass

    def bind(self, **kwargs: Any) -> "NoOpLogger":
        return self
