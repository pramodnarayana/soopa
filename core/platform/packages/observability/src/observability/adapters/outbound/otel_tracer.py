"""
OpenTelemetry Adapter — implements TracerPort using the OTel SDK.
Swap this out by registering a different TracerPort implementation in provider.py.
"""

from collections.abc import Generator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import StatusCode
from opentelemetry.util.types import AttributeValue

from observability.ports.outbound.tracer_port import SpanPort, TracerPort


class OtelSpan(SpanPort):
    """Wraps an OTel span to conform to the SpanPort port."""

    def __init__(self, span: trace.Span):
        self._span = span

    def set_attribute(self, key: str, value: AttributeValue) -> None:
        self._span.set_attribute(key, value)

    def record_exception(self, exception: Exception) -> None:
        self._span.record_exception(exception)

    def set_status_error(self, description: str) -> None:
        self._span.set_status(StatusCode.ERROR, description)


class OtelTracer(TracerPort):
    """
    OpenTelemetry implementation of TracerPort.
    Exports traces to the OTel Collector via OTLP gRPC.

    The TracerProvider is held locally on this instance to avoid the OTel global
    singleton lock. Production code uses otlp_endpoint; tests inject _span_processor.

    Args:
        service_name: The logical name of the service emitting traces.
        otlp_endpoint: Optional OTLP gRPC endpoint. Omit in tests.
        _span_processor: Optional span processor for testing. Injected via DI.
            Production code should never set this; use otlp_endpoint instead.
    """

    def __init__(
        self,
        service_name: str,
        otlp_endpoint: str | None = None,
        _span_processor: BatchSpanProcessor | SimpleSpanProcessor | None = None,
    ) -> None:
        resource = Resource(attributes={SERVICE_NAME: service_name})
        self._trace_provider = TracerProvider(resource=resource)

        if _span_processor is not None:
            self._trace_provider.add_span_processor(_span_processor)
        elif otlp_endpoint:
            trace_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            self._trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))

        self._tracer = self._trace_provider.get_tracer(service_name)

    @contextmanager
    def start_span(self, name: str) -> Generator[SpanPort, None, None]:
        with self._tracer.start_as_current_span(name) as span:
            yield OtelSpan(span)
