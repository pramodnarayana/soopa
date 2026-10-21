"""HTTP request and response DTOs for the Ingestion Gateway (L1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngressRecordHttpResponse(BaseModel):
    """Response returned upon successful acceptance (<20ms) of an inbound record."""

    record_id: str = Field(..., description="Unique inbound record identifier (ip_inb_...)")
    business_trace_id: str = Field(
        ..., description="End-to-end distributed business trace identifier (ip_trc_...)"
    )
    status: str = Field("ACCEPTED", description="Ingestion status: ACCEPTED")
    payload_size_bytes: int = Field(..., description="Size of raw payload in bytes")
    is_inlined: bool = Field(
        ...,
        description="True if payload is stored inlined in PostgreSQL, False if offloaded to S3",
    )
