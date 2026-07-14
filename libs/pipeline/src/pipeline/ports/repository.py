from typing import Any, Protocol

from domain.models import EdiJsonDomainModel, EdiMessageDomainModel


class EDIMessagePort(Protocol):
    """
    Focused port for EDI message lifecycle operations.
    Used by delivery workers that process raw EDI payloads.
    """

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        """Fetches an EDI Message by trace_id."""
        ...

    async def save_edi_message(
        self,
        trace_id: str,
        direction: str,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
        status: str,
        connection_type: str | None = "UNKNOWN",
        sender_id: str | None = None,
        receiver_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        outbound_route_id: str | None = None,
        tenant_id: int | None = None,
    ) -> None:
        """Stores a raw EDI message."""
        ...

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an EDI Message."""
        ...

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str,
        gs_receiver_id: str,
        transaction_type: str | None = None,
    ) -> None:
        """Updates the GS headers and transaction type of an EDI Message."""
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
        self,
        trace_id: str,
        direction: str,
        payload: dict[str, Any],
        status: str,
        transaction_type: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        """Persists a new JSON API Payload record."""
        ...

    async def save_edi_json(
        self,
        trace_id: str,
        direction: str,
        partnership_id: str | None,
        transaction_type: str | None,
        standard: str | None,
        sender_id: str | None,
        receiver_id: str | None,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        business_metadata: dict[str, Any],
        payload: dict[str, Any],
        status: str,
        tenant_id: int | None = None,
    ) -> str:
        """Persists a new EdiJson record and returns its UUID as a string."""
        ...

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        """Fetches an API Payload by trace_id."""
        ...

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        """Fetches an EdiJson record by trace_id."""
        ...

    async def update_edi_json_status(self, trace_id: str, status: str) -> None:
        """Updates the status of an EdiJson record."""
        ...

    async def update_edi_json(self, trace_id: str, **kwargs: Any) -> None:
        """Updates arbitrary fields on an EdiJson record."""
        ...

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
    ) -> None:
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
        self,
        direction: str,
        sender_id: str,
        receiver_id: str,
        transaction_type: str,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Finds the appropriate route based on ISA envelopes."""
        ...

    async def get_outbound_route(self, route_id: str) -> dict[str, Any] | None:
        """Fetches an outbound route by its ID."""
        ...

    async def get_outbound_route_by_trading_partner_id(
        self, trading_partner_id: str, tenant_id: int
    ) -> dict[str, Any] | None:
        """Fetches an outbound route by Trading Partner ID."""
        ...

    async def get_outbound_edi_header_by_route_or_partner(
        self,
        route_id: str | None = None,
        trading_partner_id: str | None = None,
        tenant_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Fetches OutboundEdiHeader by route or partner ID to get translation config like standard, ISA, etc."""
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

    async def get_webhook(self, partner_id: str) -> dict[str, Any] | None:
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
