"""
ObservabilityProvider — The composition root for all observability adapters.

This is the ONLY place in the codebase that knows which concrete adapter is being used.
All services receive the ITracer, IMetrics, and ILogger ports and never import adapters directly.

At startup, call ObservabilityProvider.configure(...) once.
Everywhere else, call ObservabilityProvider.tracer(), .metrics(), .logger(name).
"""

from .adapters.noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .ports.logger import ILogger
from .ports.metrics import IMetrics
from .ports.tracer import ITracer


class ObservabilityProvider:
    """
    Singleton registry for observability adapters.

    Default adapters are No-Op, so services work without any telemetry
    infrastructure (great for unit tests and local development).

    To activate real telemetry, call configure() at application startup.
    """

    _tracer: ITracer = NoOpTracer()
    _metrics: IMetrics = NoOpMetrics()
    _default_logger: ILogger = NoOpLogger()

    @classmethod
    def configure(
        cls,
        tracer: ITracer,
        metrics: IMetrics,
        logger: ILogger,
    ) -> None:
        """
        Registers concrete adapter implementations.
        Call once in the FastAPI lifespan startup handler.

        Example (production):
            from observability.adapters.otel import OtelTracer
            from observability.adapters.prometheus import PrometheusMetrics
            from observability.adapters.structlog_adapter import StructlogLogger

            ObservabilityProvider.configure(
                tracer=OtelTracer(service_name="as2-server", otlp_endpoint="..."),
                metrics=PrometheusMetrics(),
                logger=StructlogLogger("edi", log_level="INFO"),
            )

        Example (tests — uses built-in defaults, no infrastructure needed):
            ObservabilityProvider.configure(
                tracer=NoOpTracer(),
                metrics=NoOpMetrics(),
                logger=NoOpLogger(),
            )
        """
        cls._tracer = tracer
        cls._metrics = metrics
        cls._default_logger = logger

    @classmethod
    def tracer(cls) -> ITracer:
        return cls._tracer

    @classmethod
    def metrics(cls) -> IMetrics:
        return cls._metrics

    @classmethod
    def logger(cls, name: str = "") -> ILogger:
        """Returns a logger bound with the module name."""
        return cls._default_logger.bind(logger=name) if name else cls._default_logger
