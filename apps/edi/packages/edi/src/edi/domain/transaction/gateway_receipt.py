"""EDI API Gateway Receipt Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass

from edi.domain.transaction.record_base import EdiRecordBase
from edi.domain.types import JsonValue

__all__ = ["ApiGatewayReceipt"]


@dataclass(kw_only=True)
class ApiGatewayReceipt(EdiRecordBase):
    transaction_type: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    target_format: str | None = None
    payload: JsonValue | None = None
    storage_uri: str | None = None
    response: str | None = None
    headers: dict[str, JsonValue] | None = None
