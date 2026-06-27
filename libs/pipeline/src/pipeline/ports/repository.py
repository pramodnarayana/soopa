from typing import Any, Protocol


class RepositoryPort(Protocol):
    """
    Interface for interacting with the Tenant Data Plane Database.
    """

    async def get_edi_message(self, trace_id: str) -> dict[str, Any] | None:
        """Fetches an EDI Message by trace_id."""
        ...

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an EDI Message."""
        ...

    async def save_api_payload(
        self, trace_id: str, direction: str, s3_uri: str, status: str
    ) -> None:
        """Persists a new JSON API Payload record."""
        ...

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Publishes an event to the Transactional Outbox."""
        ...

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        """Fetches an API Payload by trace_id."""
        ...

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an API Payload."""
        ...
