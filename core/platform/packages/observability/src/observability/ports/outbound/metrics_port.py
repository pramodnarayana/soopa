"""
MetricsPort — Abstract interface for application metrics.
Business logic depends ONLY on this interface.
The concrete implementation (Prometheus, StatsD, CloudWatch, etc.) is injected at startup.
"""

from abc import ABC, abstractmethod


class MetricsPort(ABC):
    """
    Port for recording application metrics.
    Business logic calls this to record counters and timings.
    """

    @abstractmethod
    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """
        Increment a counter metric.

        Example:
            metrics.increment("as2_messages_received_total", labels={"tenant_id": "1"})
        """
        ...

    @abstractmethod
    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """
        Record a histogram/distribution observation (e.g. request duration in seconds).

        Example:
            metrics.observe("as2_message_processing_seconds", 0.042, labels={"tenant_id": "1"})
        """
        ...
