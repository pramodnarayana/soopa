import os
from typing import Any, ClassVar

from .events import DomainEvent


class AggregateRoot:
    """
    Base class for DDD Aggregates to store domain events internally.
    """

    ID_PREFIX: ClassVar[str]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._domain_events: list[DomainEvent] = []

    @classmethod
    def new_id(cls) -> str:
        return f"{cls.ID_PREFIX}_{os.urandom(12).hex()}"

    @property
    def domain_events(self) -> list[DomainEvent]:
        # Handle cases where __init__ was bypassed (e.g. some deserialization methods)
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
