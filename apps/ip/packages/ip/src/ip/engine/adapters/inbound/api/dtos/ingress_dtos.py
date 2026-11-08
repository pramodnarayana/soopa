"""HTTP request and response DTOs for the Ingestion Gateway (L1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngressRecordHttpResponse(BaseModel):
    """Response returned upon successful acceptance (<20ms) of an inbound record or batch."""

    record_id: str = Field(..., description="Unique inbound record identifier (ip_inb_...)")
    batch_id: str = Field("", description="Range Claim-Check batch identifier (ip_bch_...)")
    range_start: str = Field("", description="First inbound record identifier in batch")
    range_end: str = Field("", description="Last inbound record identifier in batch")
    count: int = Field(1, description="Count of records in the accepted range")
    trace_id: str = Field(..., description="End-to-end distributed trace identifier (ip_trc_...)")
    status: str = Field("ACCEPTED", description="Ingestion status: ACCEPTED")
    payload_size_bytes: int = Field(..., description="Size of raw payload in bytes")
    is_inlined: bool = Field(
        ...,
        description="True if payload is stored inlined in PostgreSQL, False if offloaded to S3",
    )
