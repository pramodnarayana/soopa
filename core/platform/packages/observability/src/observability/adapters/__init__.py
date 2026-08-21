"""Adapters package — concrete implementations of observability ports."""

from .noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .otel_metrics import OtelMetrics
from .otel_tracer import OtelTracer
from .structlog_logger import StructlogLogger

__all__ = [
    "NoOpLogger",
    "NoOpMetrics",
    "NoOpTracer",
    "OtelMetrics",
    "OtelTracer",
    "StructlogLogger",
]
