from dataclasses import dataclass, field
from typing import Any, ClassVar

from seedwork.utils import generate_id

from .events import DomainEvent


@dataclass(kw_only=True)
class AggregateRoot:
    """
    Base class for DDD Aggregates to store domain events internally.
    """

    ID_PREFIX: ClassVar[str]

    _domain_events: list[DomainEvent] = field(
        default_factory=list, init=False, repr=False, hash=False, compare=False
    )

    @classmethod
    def new_id(cls) -> str:
        return generate_id(cls.ID_PREFIX)

    @property
    def domain_events(self) -> list[DomainEvent]:
        if not hasattr(self, "_domain_events"):
            self._domain_events = []
        return self._domain_events

    def add_domain_event(self, event: DomainEvent) -> None:
        if not hasattr(self, "_domain_events"):
            self._domain_events = []
        self._domain_events.append(event)

    def clear_domain_events(self) -> None:
        if hasattr(self, "_domain_events"):
            self._domain_events.clear()


@dataclass(kw_only=True)
class TraceEvent:
    """
    Base class for trace events that are appended to a TracedAggregateRoot.
    """

    id: str
    tenant_id: str
    trace_id: str
    event_type: str
    actor: str
    metadata: dict[str, Any] | None = None


@dataclass(kw_only=True)
class TracedAggregateRoot(AggregateRoot):
    """
    Base class for DDD Aggregates that also support an immutable audit ledger
    of trace events and distributed lineage spanning a transaction's lifecycle.
    """

    trace_id: str
    tenant_id: str
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    _trace_events: list[TraceEvent] = field(
        default_factory=list, init=False, repr=False, hash=False, compare=False
    )

    @property
    def trace_events(self) -> list[TraceEvent]:
        if not hasattr(self, "_trace_events"):
            self._trace_events = []
        return self._trace_events

    def add_trace_event(self, event: TraceEvent) -> None:
        if not hasattr(self, "_trace_events"):
            self._trace_events = []
        self._trace_events.append(event)

    def clear_trace_events(self) -> None:
        if hasattr(self, "_trace_events"):
            self._trace_events.clear()
