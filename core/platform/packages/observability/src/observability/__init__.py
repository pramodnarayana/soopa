"""
Observability library public API.

Business logic and services should import ONLY from here:
  - Ports (interfaces): TracerPort, MetricsPort, LoggerPort
  - Provider (registry): ObservabilityProvider

Adapters are implementation details. Services should never import them directly.
"""

# Ports — the contracts business logic depends on
# Adapters — exposed for convenience at the composition root (e.g. main.py lifespan)
from .adapters.outbound.noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .adapters.outbound.otel_metrics import OtelMetrics
from .adapters.outbound.otel_tracer import OtelTracer
from .adapters.outbound.structlog_logger import StructlogLogger
from .ports.outbound.logger_port import LoggerPort
from .ports.outbound.metrics_port import MetricsPort
from .ports.outbound.tracer_port import SpanPort, TracerPort

# Provider — the single composition root
from .provider import ObservabilityProvider

__all__ = [  # noqa: RUF022 - intentionally grouped by layer: Ports → Provider → Adapters
    # Ports
    "TracerPort",
    "SpanPort",
    "MetricsPort",
    "LoggerPort",
    # Provider
    "ObservabilityProvider",
    # Adapters (for use in composition root only)
    "NoOpTracer",
    "NoOpMetrics",
    "NoOpLogger",
    "OtelTracer",
    "OtelMetrics",
    "StructlogLogger",
]
