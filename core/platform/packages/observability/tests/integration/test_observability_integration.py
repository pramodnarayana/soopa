import pytest

from observability.adapters.outbound.otel_tracer import OtelTracer
from observability.adapters.outbound.structlog_logger import StructlogLogger

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_observability_structlog_instantiation():
    """
    Test that the structlog logger can be initialized and
    methods can be called without exception.
    """
    logger = StructlogLogger(name="test_integration_logger")
    logger.info("integration_test_event", payload={"key": "value"})


@pytest.mark.integration
async def test_observability_otel_tracer_instantiation():
    """
    Test that OtelTracer can be instantiated and a span can be started.
    """
    tracer = OtelTracer(service_name="test_integration_service")
    with tracer.start_span("integration_test_span") as span:
        span.set_attribute("integration.test.key", "integration.test.value")
