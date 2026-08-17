"""
ITracer Port — Abstract interface for distributed tracing.
Business logic depends ONLY on this interface.
The concrete implementation (OpenTelemetry, Datadog, etc.) is injected at startup.
"""

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


class ISpan(ABC):
    """Represents a single unit of work in a distributed trace."""

    @abstractmethod
    def set_attribute(self, key: str, value: Any) -> None:
        """Attach a key-value attribute to the span for querying in the UI."""
        ...

    @abstractmethod
    def record_exception(self, exception: Exception) -> None:
        """Record an exception event on the span."""
        ...

    @abstractmethod
    def set_status_error(self, description: str) -> None:
        """Mark the span as failed."""
        ...


class ITracer(ABC):
    """
    Port for distributed tracing.
    Business logic calls this to instrument code paths.
    """

    @abstractmethod
    @contextmanager
    def start_span(self, name: str) -> Generator[ISpan, None, None]:
        """
        Context manager that creates and activates a span.

        Usage:
            with tracer.start_span("as2.decrypt") as span:
                span.set_attribute("message_id", msg.message_id)
                ...
        """
        ...
