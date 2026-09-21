from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonValue

from edi.domain.enums import EdiDirection, MessageStatus


@dataclass(frozen=True, kw_only=True)
class ApiGatewayPayloadDTO:
    id: str
    trace_id: str
    payload: JsonValue | None
    status: str
    http_status_code: int | None
    response: str | None


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


class ApiGatewayRepositoryPort(Protocol):
    """
    Port for the ApiGateway aggregate, managing the immutable infrastructure log
    of HTTP delivery attempts and their statuses.
    """

    async def create_api_gateway(self, command: CreateApiGatewayCommand) -> str:
        """
        Creates an API Gateway record.
        """
        ...

    async def get_api_payload(self, trace_id: str) -> ApiGatewayPayloadDTO | None:
        """
        Fetches the latest API Gateway record for the given trace_id.
        """
        ...

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
        record_id: str | None = None,
    ) -> None:
        """
        Updates the status of an API Gateway record.
        """
        ...
