from typing import Any, Protocol


class EventTranslatorPort(Protocol):
    def translate_external_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Translate an external event into an internal domain event. Returns None if unknown."""
        ...
