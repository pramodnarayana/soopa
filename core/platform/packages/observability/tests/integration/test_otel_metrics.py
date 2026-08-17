import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from observability.adapters.otel_metrics import OtelMetrics


@pytest.fixture
def memory_reader():
    # Create a memory reader for testing
    return InMemoryMetricReader()


@pytest.fixture
def otel_metrics(memory_reader, monkeypatch):
    # Patch OtelMetrics to use the memory reader for testing
    def patched_init(self, service_name, otlp_endpoint=None):
        # Call original init but ignore otlp_endpoint
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource

        self._service_name = service_name
        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = MeterProvider(resource=resource, metric_readers=[memory_reader])
        metrics.set_meter_provider(provider)
        self._meter = provider.get_meter(service_name)
        self._counters = {}
        self._histograms = {}

    monkeypatch.setattr(OtelMetrics, "__init__", patched_init)
    metrics_adapter = OtelMetrics(service_name="test-service")
    return metrics_adapter


def test_otel_metrics_increment(otel_metrics, memory_reader):
    otel_metrics.increment("login_attempts", 2.0, labels={"status": "success"})
    otel_metrics.increment("login_attempts", 1.0, labels={"status": "success"})

    metrics_data = memory_reader.get_metrics_data()
    assert metrics_data is not None

    resource_metrics = metrics_data.resource_metrics[0]
    scope_metrics = resource_metrics.scope_metrics[0]

    # Find the specific metric by name
    metric = next((m for m in scope_metrics.metrics if m.name == "login_attempts"), None)
    assert metric is not None, "login_attempts metric not found"

    assert len(metric.data.data_points) == 1
    point = next(iter(metric.data.data_points))

    assert point.value == 3.0
    assert point.attributes["status"] == "success"


def test_otel_metrics_observe(otel_metrics, memory_reader):
    otel_metrics.observe("request_duration", 0.5, labels={"endpoint": "/api/users"})
    otel_metrics.observe("request_duration", 1.5, labels={"endpoint": "/api/users"})

    metrics_data = memory_reader.get_metrics_data()
    assert metrics_data is not None

    resource_metrics = metrics_data.resource_metrics[0]
    scope_metrics = resource_metrics.scope_metrics[0]

    # Find the specific metric by name
    metric = next((m for m in scope_metrics.metrics if m.name == "request_duration"), None)
    assert metric is not None, "request_duration metric not found"

    assert len(metric.data.data_points) == 1
    point = next(iter(metric.data.data_points))

    assert point.count == 2
    assert point.sum == 2.0
    assert point.attributes["endpoint"] == "/api/users"
