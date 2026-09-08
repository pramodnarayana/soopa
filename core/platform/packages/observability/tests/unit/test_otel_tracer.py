from opentelemetry.sdk.trace import TracerProvider

from observability.adapters.outbound.otel_tracer import OtelTracer


def test_otel_tracer_exposes_its_local_trace_provider() -> None:
    tracer = OtelTracer(service_name="test-service")

    assert isinstance(tracer.trace_provider, TracerProvider)
