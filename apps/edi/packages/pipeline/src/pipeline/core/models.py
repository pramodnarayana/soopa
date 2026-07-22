from typing import Any

from pydantic import BaseModel


class EdiWebhookMetadata(BaseModel):
    trace_id: str
    direction: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    trading_partner_id: str | None = None
    format_standard: str | None = None


class EdiWebhookPayload(BaseModel):
    metadata: EdiWebhookMetadata
    transactions: list[dict[str, Any]] | None = None

    @classmethod
    def build(
        cls,
        trace_id: str,
        direction: str | None,
        sender_id: str | None,
        receiver_id: str | None,
        trading_partner_id: str | None,
        format_standard: str | None,
        transactions: list[dict[str, Any]] | None,
    ) -> "EdiWebhookPayload":
        """
        Enterprise factory method to build a strongly-typed webhook payload
        completely decoupled from the internal database representation (edi_message).
        """
        metadata = EdiWebhookMetadata(
            trace_id=trace_id,
            direction=direction,
            sender_id=sender_id,
            receiver_id=receiver_id,
            trading_partner_id=trading_partner_id,
            format_standard=format_standard,
        )
        return cls(metadata=metadata, transactions=transactions)
