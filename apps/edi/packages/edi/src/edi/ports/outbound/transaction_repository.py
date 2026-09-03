from collections.abc import Sequence
from typing import Protocol

from seedwork.domain.types import JsonValue

from edi.application.dtos.routes import InboundRouteDTO
from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.application.dtos.webhooks import WebhookDTO
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel


class TransactionRepositoryPort(Protocol):
    """
    Port for the Data Plane transaction repository, handling Operational Data.
    """

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        """
        Fetches an EDI Message by trace_id and maps it to the domain model.
        """
        ...

    async def get_route(
        self, direction: str, sender_id: str, receiver_id: str, transaction_type: str
    ) -> InboundRouteDTO | None:
        """
        Fetches a route config for the Data Plane and returns a typed DTO.
        """
        ...

    async def get_webhook(self, partner_id: str) -> WebhookDTO | None:
        """
        Fetches Webhook partner config and returns a typed DTO.
        """
        ...

    async def save_api_payload(
        self,
        trace_id: str,
        direction: str,
        payload: dict[str, JsonValue],
        status: str,
        transaction_type: str | None = None,
        webhook_url: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """
        Saves API payload.
        """
        ...

    async def create_edi_message(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        """
        Saves a new EdiMessage record to the Data Plane.
        """
        ...

    async def save(self, aggregate: EdiMessageDomainModel) -> None:
        """
        Persists the aggregate state and drains any domain events into the outbox
        within the same transaction. This is the DDD-compliant way to publish events.
        """
        ...

    async def save_json(self, aggregate: EdiJsonDomainModel) -> None:
        """
        Persists the EdiJson aggregate state and drains any domain events into the outbox
        within the same transaction.
        """
        ...

    async def create_edi_json(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        """
        Saves a new EdiJson record to the Data Plane.
        """
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
        business_metadata: dict[str, JsonValue],
        payload: dict[str, JsonValue],
        status: str,
        tenant_id: str | None = None,
    ) -> str:
        """
        Upserts an EdiJson record.
        """
        ...

    async def create_api_gateway(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        """
        Saves a new ApiGateway record to the Data Plane.
        """
        ...

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessageDTO]:
        """
        Lists transactions joined across Data Plane tables.
        """
        ...

    async def explorer_list_edi_messages(
        self, tenant_id: str, filters: list[dict[str, JsonValue]], limit: int = 50, offset: int = 0
    ) -> Sequence[EdiMessageDTO]:
        """
        Dynamically query EdiMessage for the data explorer.
        """
        ...

    async def explorer_list_edi_json(
        self, tenant_id: str, filters: list[dict[str, JsonValue]], limit: int = 50, offset: int = 0
    ) -> Sequence[EdiJsonDTO]:
        """
        Dynamically query EdiJson for the data explorer.
        """
        ...

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJsonDTO]:
        """
        Retrieves a chronological thread of documents sharing a specific business metadata key/value.
        """
        ...

    async def get_existing_trace_ids(self, tenant_id: str, trace_ids: list[str]) -> set[str]:
        """
        Takes a list of trace_ids and returns the subset that actually exist in the DB.
        """
        ...
