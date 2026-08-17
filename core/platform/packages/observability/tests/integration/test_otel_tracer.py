import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability.adapters.otel import OtelTracer

# Global setup for TracerProvider
_memory_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture
def memory_exporter():
    _memory_exporter.clear()
    return _memory_exporter


@pytest.fixture
def otel_tracer(memory_exporter):
    tracer = OtelTracer(service_name="test-service")
    return tracer


def test_otel_tracer_start_span(otel_tracer, memory_exporter):
    with otel_tracer.start_span("test-span") as span:
        span.set_attribute("user_id", "123")
        span.set_attribute("tenant_id", "abc")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1

    exported_span = spans[0]
    assert exported_span.name == "test-span"
    assert exported_span.attributes["user_id"] == "123"
    assert exported_span.attributes["tenant_id"] == "abc"


def test_otel_tracer_record_exception(otel_tracer, memory_exporter):
    with pytest.raises(ValueError), otel_tracer.start_span("failing-span") as span:
        span.set_status_error("Failed completely")
        raise ValueError("Something went wrong")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1

    exported_span = spans[0]
    assert exported_span.name == "failing-span"
    assert not exported_span.status.is_ok

    # Events hold the recorded exception
    assert len(exported_span.events) == 1
    assert exported_span.events[0].name == "exception"
    assert exported_span.events[0].attributes["exception.type"] == "ValueError"
    assert exported_span.events[0].attributes["exception.message"] == "Something went wrong"
