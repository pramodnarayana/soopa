"""
OpenTelemetry Metrics Adapter — implements MetricsPort using the OTel SDK.
Swap this out by registering a different MetricsPort implementation in provider.py.
"""

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from observability.ports.outbound.metrics_port import MetricsPort


class OtelMetrics(MetricsPort):
    """
    OpenTelemetry implementation of MetricsPort.
    Counters and histograms are created on first use and cached.

    Args:
        service_name: The logical name of the service emitting metrics.
        otlp_endpoint: Optional OTLP gRPC endpoint. Omit in tests.
        _metric_reader: Optional metric reader for testing. Injected via DI.
            Production code should never set this; use otlp_endpoint instead.
    """

    def __init__(
        self,
        service_name: str,
        otlp_endpoint: str | None = None,
        _metric_reader: PeriodicExportingMetricReader | InMemoryMetricReader | None = None,
    ) -> None:
        self._service_name = service_name

        resource = Resource(attributes={SERVICE_NAME: service_name})

        if _metric_reader is not None:
            provider = MeterProvider(resource=resource, metric_readers=[_metric_reader])
        elif otlp_endpoint:
            exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
            reader = PeriodicExportingMetricReader(exporter)
            provider = MeterProvider(resource=resource, metric_readers=[reader])
        else:
            provider = MeterProvider(resource=resource)

        metrics.set_meter_provider(provider)
        self._meter = provider.get_meter(service_name)

        # Cache for instruments
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def _get_or_create_counter(self, name: str) -> Counter:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(
                name=name,
                description=f"Counter metric: {name}",
            )
        return self._counters[name]

    def _get_or_create_histogram(self, name: str) -> Histogram:
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
