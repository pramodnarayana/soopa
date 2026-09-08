"""
Unit tests for OtelMetrics adapter.

These tests verify that OtelMetrics correctly:
- Accumulates counter values across multiple increments
- Records histogram observations and computes sum/count

No faking is used. The OtelMetrics accepts an optional _metric_reader via DI,
which allows injecting an InMemoryMetricReader for inspection without monkeypatching.
"""

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from observability.adapters.outbound.otel_metrics import OtelMetrics


@pytest.fixture
def memory_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def otel_metrics(memory_reader: InMemoryMetricReader) -> OtelMetrics:
    """Creates OtelMetrics with a DI-injected in-memory reader. No monkeypatching."""
    return OtelMetrics(
        service_name="test-service",
        _metric_reader=memory_reader,
    )


def test_otel_metrics_increment_accumulates_counter(
    otel_metrics: OtelMetrics, memory_reader: InMemoryMetricReader
) -> None:
    otel_metrics.increment("login_attempts", 2.0, labels={"status": "success"})
    otel_metrics.increment("login_attempts", 1.0, labels={"status": "success"})

    metrics_data = memory_reader.get_metrics_data()
    assert metrics_data is not None

    resource_metrics = metrics_data.resource_metrics[0]
    scope_metrics = resource_metrics.scope_metrics[0]

    metric = next((m for m in scope_metrics.metrics if m.name == "login_attempts"), None)
    assert metric is not None, "login_attempts metric not found"

    assert len(metric.data.data_points) == 1
    point = next(iter(metric.data.data_points))

    assert point.value == 3.0
    assert point.attributes["status"] == "success"


def test_otel_metrics_observe_records_histogram(
    otel_metrics: OtelMetrics, memory_reader: InMemoryMetricReader
) -> None:
    otel_metrics.observe("request_duration", 0.5, labels={"endpoint": "/api/users"})
    otel_metrics.observe("request_duration", 1.5, labels={"endpoint": "/api/users"})

    metrics_data = memory_reader.get_metrics_data()
    assert metrics_data is not None

    resource_metrics = metrics_data.resource_metrics[0]
    scope_metrics = resource_metrics.scope_metrics[0]

    metric = next((m for m in scope_metrics.metrics if m.name == "request_duration"), None)
    assert metric is not None, "request_duration metric not found"

    assert len(metric.data.data_points) == 1
    point = next(iter(metric.data.data_points))

    assert point.count == 2
    assert point.sum == 2.0
    assert point.attributes["endpoint"] == "/api/users"
