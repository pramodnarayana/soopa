from identity.domain.events import DomainEvent


class AggregateRoot:
    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    @property
    def domain_events(self) -> list[DomainEvent]:
        return self._domain_events

    def add_domain_event(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def clear_domain_events(self) -> None:
        self._domain_events.clear()
