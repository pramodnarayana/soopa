"""
Observability Bootstrap for the Unified API Shell.

Configures OpenTelemetry Tracing, Structlog (JSON Logging), and Prometheus Metrics.
This wiring occurs at the composition root and uses the shared `observability` package.
"""

import os

from fastapi import FastAPI
from observability import NoOpMetrics, ObservabilityProvider, OtelTracer, StructlogLogger
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


def setup_observability(app: FastAPI) -> None:
    """
    Configures the Enterprise Observability stack for the Unified API.
    """
    # In a real environment, this would come from Settings.
    # We fallback to None for local development to avoid connection errors
    otlp_endpoint = os.getenv("OTLP_ENDPOINT")
    service_name = "soopa-unified-api"
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # 1. Initialize the concrete adapters
    tracer = OtelTracer(service_name=service_name, otlp_endpoint=otlp_endpoint)
    logger = StructlogLogger(name="unified_api", log_level=log_level)
    metrics = NoOpMetrics()  # To be replaced with PrometheusMetrics later

    # 2. Register with the global provider
    ObservabilityProvider.configure(
        tracer=tracer,
        metrics=metrics,
        logger=logger,
    )

    # 3. Instrument the FastAPI application to automatically generate traces for HTTP requests
    FastAPIInstrumentor.instrument_app(app)

    # Let the log system know we started
    ObservabilityProvider.logger(__name__).info(
        "observability_configured", service=service_name, otlp_endpoint=otlp_endpoint
    )
