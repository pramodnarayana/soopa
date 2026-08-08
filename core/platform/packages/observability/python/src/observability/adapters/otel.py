"""
OpenTelemetry Adapter — implements ITracer using the OTel SDK.
Swap this out by registering a different ITracer implementation in provider.py.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode

from ..ports.tracer import ISpan, ITracer


class OtelSpan(ISpan):
    """Wraps an OTel span to conform to the ISpan port."""

    def __init__(self, span: trace.Span):
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)

    def record_exception(self, exception: Exception) -> None:
        self._span.record_exception(exception)

    def set_status_error(self, description: str) -> None:
        self._span.set_status(StatusCode.ERROR, description)


class OtelTracer(ITracer):
    """
    OpenTelemetry implementation of ITracer.
    Exports traces to the OTel Collector via OTLP gRPC.
    """

    def __init__(self, service_name: str, otlp_endpoint: str | None = None):
        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)

        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer(service_name)

    @contextmanager
    def start_span(self, name: str) -> Generator[ISpan, None, None]:
        with self._tracer.start_as_current_span(name) as span:
            yield OtelSpan(span)
