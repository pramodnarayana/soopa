"""
OpenTelemetry Metrics Adapter — implements IMetrics using the OTel SDK.
Swap this out by registering a different IMetrics implementation in provider.py.
"""

from typing import Any

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from ..ports.metrics import IMetrics


class OtelMetrics(IMetrics):
    """
    OpenTelemetry implementation of IMetrics.
    Counters and histograms are created on first use and cached.
    """

    def __init__(self, service_name: str, otlp_endpoint: str | None = None):
        self._service_name = service_name

        resource = Resource(attributes={SERVICE_NAME: service_name})

        if otlp_endpoint:
            exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
            reader = PeriodicExportingMetricReader(exporter)
            provider = MeterProvider(resource=resource, metric_readers=[reader])
        else:
            provider = MeterProvider(resource=resource)

        metrics.set_meter_provider(provider)
        self._meter = provider.get_meter(service_name)

        # Cache for instruments
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    def _get_or_create_counter(self, name: str) -> Any:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(
                name=name,
                description=f"Counter metric: {name}",
            )
        return self._counters[name]

    def _get_or_create_histogram(self, name: str) -> Any:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(
                name=name,
                description=f"Histogram metric: {name}",
            )
        return self._histograms[name]

    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        counter = self._get_or_create_counter(name)
        counter.add(value, attributes=labels or {})

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        histogram = self._get_or_create_histogram(name)
        histogram.record(value, attributes=labels or {})
