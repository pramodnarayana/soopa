"""
ObservabilityProvider — The composition root for all observability adapters.

This is the ONLY place in the codebase that knows which concrete adapter is being used.
All services receive the TracerPort, MetricsPort, and LoggerPort ports and never import adapters directly.

At startup, call ObservabilityProvider.configure(...) once.
Everywhere else, call ObservabilityProvider.tracer(), .metrics(), .logger(name).
"""

import os

from .adapters.outbound.noop import NoOpLogger, NoOpMetrics, NoOpTracer
from .adapters.outbound.otel_tracer import OtelTracer
from .adapters.outbound.structlog_logger import StructlogLogger
from .ports.outbound.logger_port import LoggerPort
from .ports.outbound.metrics_port import MetricsPort
from .ports.outbound.tracer_port import TracerPort


class ObservabilityProvider:
    """
    Singleton registry for observability adapters.

    Default adapters are No-Op, so services work without any telemetry
    infrastructure (great for unit tests and local development).

    To activate real telemetry, call configure() at application startup.
    """

    _tracer: TracerPort = NoOpTracer()
    _metrics: MetricsPort = NoOpMetrics()
    _default_logger: LoggerPort = NoOpLogger()

    @classmethod
    def configure(
        cls,
        tracer: TracerPort,
        metrics: MetricsPort,
        logger: LoggerPort,
    ) -> None:
        """
        Registers concrete adapter implementations.
        Call once in the FastAPI lifespan startup handler.

        Example (production):
            from observability.adapters.outbound.otel_tracer import OtelTracer
            from observability.adapters.outbound.otel_metrics import OtelMetrics
            from observability.adapters.outbound.structlog_logger import StructlogLogger

            ObservabilityProvider.configure(
                tracer=OtelTracer(service_name="as2-server", otlp_endpoint="..."),
                metrics=OtelMetrics(service_name="as2-server", otlp_endpoint="..."),
                logger=StructlogLogger(
                    name="edi",
                    log_level="INFO",
                    service_name="as2-server",
                    otlp_endpoint="..."
                ),
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
    def auto_configure_from_env(cls, service_name: str) -> None:
        """
        Automatically reads OTLP_ENDPOINT and LOG_LEVEL from the environment and configures all adapters.
        Use this to prevent duplicating composition root logic across workers and APIs.
        """
        otlp_endpoint = os.getenv("OTLP_ENDPOINT")
        log_level = os.getenv("LOG_LEVEL", "INFO")

        cls.configure(
            tracer=OtelTracer(service_name=service_name, otlp_endpoint=otlp_endpoint),
            metrics=NoOpMetrics(),  # OtelMetrics implementation pending
            logger=StructlogLogger(
                name=service_name,
                log_level=log_level,
                service_name=service_name,
                otlp_endpoint=otlp_endpoint,
            ),
        )

    @classmethod
    def tracer(cls) -> TracerPort:
        return cls._tracer

    @classmethod
    def metrics(cls) -> MetricsPort:
        return cls._metrics

    @classmethod
    def logger(cls, name: str = "") -> LoggerPort:
        """Returns a logger bound with the module name."""
        return cls._default_logger.bind(logger=name) if name else cls._default_logger
