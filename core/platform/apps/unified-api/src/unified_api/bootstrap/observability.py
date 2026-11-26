"""
Observability Bootstrap for the Unified API Shell.

Configures OpenTelemetry Tracing, Structlog (JSON Logging), and Prometheus Metrics.
This wiring occurs at the composition root and uses the shared `observability` package.
"""

import os

from fastapi import FastAPI
from observability import NoOpMetrics, ObservabilityProvider, OtelTracer, StructlogLogger
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware


def setup_observability(app: FastAPI, *, service_name: str = "soopa-unified-api") -> None:
    """
    Configures the Enterprise Observability stack for Unified API & Watch Gateway containers.
    """
    # In a real environment, this would come from Settings.
    # We fallback to None for local development to avoid connection errors
    otlp_endpoint = os.getenv("OTLP_ENDPOINT")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # 1. Initialize the concrete adapters
    tracer = OtelTracer(service_name=service_name, otlp_endpoint=otlp_endpoint)
    logger = StructlogLogger(name=service_name, log_level=log_level)
    metrics = NoOpMetrics()  # To be replaced with PrometheusMetrics later

    # 2. Register with the global provider
    ObservabilityProvider.configure(
        tracer=tracer,
        metrics=metrics,
        logger=logger,
    )

    # 3. Instrument the FastAPI application to automatically generate traces for HTTP requests
    # Use ASGI middleware to avoid the FastAPIInstrumentor OPTIONS crash with _IncludedRouter
    app.add_middleware(OpenTelemetryMiddleware, tracer_provider=tracer.trace_provider)

    # Let the log system know we started
    ObservabilityProvider.logger(__name__).info(
        "observability_configured", service=service_name, otlp_endpoint=otlp_endpoint
    )
