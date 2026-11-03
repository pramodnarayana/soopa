from __future__ import annotations

from typing import Protocol

from seedwork.domain.types import JsonDict

from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt


class ApiGatewayRepositoryPort(Protocol):
    """Port for the Data-Plane ApiGatewayReceipt stage aggregate repository."""

    async def save(self, receipt: ApiGatewayReceipt) -> str: ...

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayReceipt]: ...

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: MessageStatus,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        record_id: str | None = None,
    ) -> None: ...


__all__ = [
    "ApiGatewayRepositoryPort",
]
