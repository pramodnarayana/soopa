"""
Observability library public API.

Business logic and services should import ONLY from here:
  - Ports (interfaces): ITracer, IMetrics, ILogger
  - Provider (registry): ObservabilityProvider

Adapters are implementation details. Services should never import them directly.
"""

# Ports — the contracts business logic depends on
# Adapters — exposed for convenience at the composition root (e.g. main.py lifespan)
from .adapters.noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .adapters.otel import OtelTracer
from .adapters.prometheus import PrometheusMetrics
from .adapters.structlog_adapter import StructlogLogger
from .ports.logger import ILogger
from .ports.metrics import IMetrics
from .ports.tracer import ISpan, ITracer

# Provider — the single composition root
from .provider import ObservabilityProvider

__all__ = [
    # Ports
    "ITracer",
    "ISpan",
    "IMetrics",
    "ILogger",
    # Provider
    "ObservabilityProvider",
    # Adapters (for use in composition root only)
    "NoOpTracer",
    "NoOpMetrics",
    "NoOpLogger",
    "OtelTracer",
    "PrometheusMetrics",
    "StructlogLogger",
]
