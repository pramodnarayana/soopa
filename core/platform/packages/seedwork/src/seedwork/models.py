from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from seedwork.utils import generate_id

from .events import DomainEvent


@dataclass(kw_only=True, eq=False)
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
