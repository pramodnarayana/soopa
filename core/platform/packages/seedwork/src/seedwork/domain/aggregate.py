from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from seedwork.events import DomainEvent
from seedwork.utils import generate_id


@dataclass(kw_only=True, eq=False)
class AggregateRoot:
    """Base class for DDD Aggregates to store domain events internally."""

    ID_PREFIX: ClassVar[str]

    _domain_events: list[DomainEvent] = field(
        default_factory=list, init=False, repr=False, hash=False, compare=False
    )

    @classmethod
    def new_id(cls) -> str:
        return generate_id(cls.ID_PREFIX)

    def _ensure_domain_events(self) -> list[DomainEvent]:
        try:
            return self._domain_events
        except AttributeError:
            self._domain_events = []
            return self._domain_events

    @property
    def domain_events(self) -> list[DomainEvent]:
        return self._ensure_domain_events()

    def add_domain_event(self, event: DomainEvent) -> None:
        self._ensure_domain_events().append(event)

    def clear_domain_events(self) -> None:
        self._ensure_domain_events().clear()

    def pull_domain_events(self) -> list[DomainEvent]:
        """Atomically pull and drain all pending domain events recorded by this aggregate."""
        bucket = self._ensure_domain_events()
        events = list(bucket)
        bucket.clear()
        return events


__all__ = ["AggregateRoot"]
