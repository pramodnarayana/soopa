from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonValue

from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.domain.enums import (
    ConnectionType,
    EdiDirection,
    EdiStandard,
    EncryptionAlgorithm,
    MDNType,
    MessageStatus,
    SignatureAlgorithm,
)
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel

# ---------------------------------------------------------------------------
# Data-Plane Port Commands
# These are the typed contract of the TransactionRepositoryPort — each
# command describes exactly what the port accepts. They live here so that
# every caller can depend on the port package alone (hexagonal architecture).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class CreateEdiMessageCommand:
    trace_id: str
    tenant_id: str
    id: str | None = None
    direction: EdiDirection | None = None
    connection_type: ConnectionType | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    as2_sender_id: str | None = None
    as2_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    message_id: str | None = None
    mdn_id: str | None = None
    mdn_mode: MDNType | None = None
    mdn_response: str | None = None
    file_name: str | None = None
    content_type: str | None = None
    signature_algorithm: SignatureAlgorithm | None = None
    encryption_algorithm: EncryptionAlgorithm | None = None
    trading_partner_id: str | None = None
    status: MessageStatus | None = None
    edi_data: str | None = None
    interchange_control_no: str | None = None
    transaction_type: str | None = None
    format_standard: EdiStandard | str | None = None
    storage_uri: str | None = None
    file_size_bytes: int | None = None
    msg_headers: dict[str, JsonValue] | None = None
    state: str | None = None
    status_message: str | None = None
    is_resend: bool | None = None
    parent_trace_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class CreateEdiJsonCommand:
    trace_id: str
    tenant_id: str
    id: str | None = None
    direction: EdiDirection | None = None
    status: MessageStatus | None = None
    trading_partner_id: str | None = None
    standard: str | None = None
    business_metadata: dict[str, JsonValue] | None = None
    transaction_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    payload: JsonValue | None = None
    parent_trace_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class CreateApiGatewayCommand:
    trace_id: str
    tenant_id: str
    id: str | None = None
    direction: EdiDirection | None = None
    status: MessageStatus | None = None
    transaction_type: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    payload: JsonValue | None = None
    response: str | None = None
    parent_trace_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class UpdateEdiJsonCommand:
    """Typed command for partial updates to an existing EdiJson record."""

    trace_id: str
    trading_partner_id: str | None = None
    standard: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None


class TransactionRepositoryPort(Protocol):
    """
    Port for the Data Plane transaction repository, handling Operational Data.
    """

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        """
        Fetches an EDI Message by trace_id and maps it to the domain model.
        """
        ...

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        """
        Fetches an EDI JSON record by trace_id and maps it to the domain model.
        """
        ...

    async def create_api_gateway(self, command: CreateApiGatewayCommand) -> str:
        """
        Saves a new ApiGateway record to the Data Plane.
        """
        ...

    async def claim_api_payload(self, trace_id: str) -> bool: ...

    async def get_api_payload(self, trace_id: str) -> dict[str, JsonValue] | None: ...

    async def claim_edi_message(self, trace_id: str) -> bool: ...

    async def create_edi_message(self, command: CreateEdiMessageCommand) -> str:
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

    async def create_edi_json(self, command: CreateEdiJsonCommand) -> str:
        """
        Saves a new EdiJson record to the Data Plane.
        """
        ...

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        transaction_type: str | None,
    ) -> None:
        """
        Updates metadata fields on an existing EdiMessage.
        """
        ...

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        """
        Updates the status of an existing EdiMessage.
        """
        ...

    async def update_edi_json(self, command: UpdateEdiJsonCommand) -> None:
        """
        Applies a partial update to an existing EdiJson record using a typed command.
        """
        ...

    async def update_edi_json_status(self, trace_id: str, status: str) -> None:
        """
        Updates the status of an existing EdiJson record.
        """
        ...

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
    ) -> None:
        """
        Updates the status of an existing ApiGateway payload.
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

    async def get_edi_json_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> EdiJsonDTO | None:
        """
        Retrieves an EdiJson record by its idempotency key (stored in business_metadata).
        """
        ...
