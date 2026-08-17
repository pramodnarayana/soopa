"""Adapters package — concrete implementations of observability ports."""

from .noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .otel import OtelTracer
from .otel_metrics import OtelMetrics
from .structlog_adapter import StructlogLogger

__all__ = [
    "NoOpLogger",
    "NoOpMetrics",
    "NoOpTracer",
    "OtelMetrics",
    "OtelTracer",
    "StructlogLogger",
]
