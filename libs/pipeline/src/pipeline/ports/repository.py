from typing import Any, Protocol


class EDIMessagePort(Protocol):
    """
    Focused port for EDI message lifecycle operations.
    Used by delivery workers that process raw EDI payloads.
    """

    async def get_edi_message(self, trace_id: str) -> dict[str, Any] | None:
        """Fetches an EDI Message by trace_id."""
        ...

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an EDI Message."""
        ...

    async def claim_edi_message(self, trace_id: str) -> bool:
        """Atomically claims an EDI message (CAS: PENDING_DELIVERY → PROCESSING)."""
        ...


class APIPayloadPort(Protocol):
    """
    Focused port for API payload lifecycle operations.
    Used by delivery workers that process JSON payloads destined for webhooks.
    """

    async def save_api_payload(
        self, trace_id: str, direction: str, s3_uri: str, status: str
    ) -> None:
        """Persists a new JSON API Payload record."""
        ...

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        """Fetches an API Payload by trace_id."""
        ...

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an API Payload."""
        ...

    async def claim_api_payload(self, trace_id: str) -> bool:
        """Atomically claims an API Payload for delivery (CAS: PENDING_DELIVERY → PROCESSING)."""
        ...


class RoutePort(Protocol):
    """
    Focused port for route and outbox operations.
    Used by workers that need to resolve delivery destinations and publish events.
    """

    async def get_route(
        self, direction: str, sender_id: str, receiver_id: str, transaction_type: str
    ) -> dict[str, Any] | None:
        """Finds the appropriate route based on ISA envelopes."""
        ...

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Publishes an event to the Transactional Outbox."""
        ...


class PartnerPort(Protocol):
    """
    Focused port for trading partner config lookups.
    Used by delivery workers to resolve partner credentials and endpoints.
    """

    async def get_sftp_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches SFTP partner config."""
        ...

    async def get_webhook_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches Webhook partner config."""
        ...

    async def get_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches AS2 partner config (remote partner + partnership settings)."""
        ...

    async def get_local_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches the local AS2 partner (our entity) for signing key and cert refs."""
        ...


class RepositoryPort(EDIMessagePort, APIPayloadPort, RoutePort, PartnerPort, Protocol):
    """
    Composed repository port — the full contract for the Tenant Data Plane.
    Concrete adapters implement this. Individual services should prefer
    the narrower sub-protocols (EDIMessagePort, RoutePort, etc.) where possible.
    """

    ...
