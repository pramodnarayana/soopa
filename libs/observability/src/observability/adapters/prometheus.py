"""
Prometheus Adapter — implements IMetrics using prometheus_client.
Swap this out by registering a different IMetrics implementation in provider.py.
"""

from prometheus_client import Counter, Histogram

from ..ports.metrics import IMetrics


class PrometheusMetrics(IMetrics):
    """
    Prometheus implementation of IMetrics.
    Counters and histograms are created on first use and cached.
    All metrics are namespaced under 'edi_'.
    """

    def __init__(self, namespace: str = "edi"):
        self._namespace = namespace
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def _get_or_create_counter(self, name: str, labels: dict | None) -> Counter:
        label_names = sorted(labels.keys()) if labels else []
        key = f"{name}:{','.join(label_names)}"
        if key not in self._counters:
            self._counters[key] = Counter(
                f"{self._namespace}_{name}",
                f"Counter metric: {name}",
                labelnames=label_names,
            )
        return self._counters[key]

    def _get_or_create_histogram(self, name: str, labels: dict | None) -> Histogram:
        label_names = sorted(labels.keys()) if labels else []
        key = f"{name}:{','.join(label_names)}"
        if key not in self._histograms:
            self._histograms[key] = Histogram(
                f"{self._namespace}_{name}",
                f"Histogram metric: {name}",
                labelnames=label_names,
                buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            )
        return self._histograms[key]

    def increment(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        counter = self._get_or_create_counter(name, labels or {})
        if labels:
            counter.labels(**labels).inc(value)
        else:
            counter.inc(value)

    def observe(self, name: str, value: float, labels: dict | None = None) -> None:
        histogram = self._get_or_create_histogram(name, labels or {})
        if labels:
            histogram.labels(**labels).observe(value)
        else:
            histogram.observe(value)
