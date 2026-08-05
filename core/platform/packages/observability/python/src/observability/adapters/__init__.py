"""Adapters package — concrete implementations of observability ports."""

from .noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .otel import OtelTracer
from .prometheus import PrometheusMetrics
from .structlog_adapter import StructlogLogger

__all__ = [
    "NoOpLogger",
    "NoOpMetrics",
    "NoOpTracer",
    "OtelTracer",
    "PrometheusMetrics",
    "StructlogLogger",
]
