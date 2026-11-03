from typing import Protocol

from seedwork.domain.types import JsonDict


class EventTranslatorPort(Protocol):
    def translate_external_event(self, event_type: str, payload: JsonDict) -> JsonDict | None:
        """Translate an external event into an internal domain event. Returns None if unknown."""
        ...
