"""Return-leg callback envelope value object for Layer 5 -> Layer 1 ingress loopback."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict


@dataclass(frozen=True, kw_only=True)
class ResponseEventEnvelope:
    """Immutable value object packaging a generated destination identifier for L1 return-leg loopback."""

    outbound_record_id: str
    source_record_id: str
    destination_id: str
    connection_id: str
    app_id: str
    stream_name: str
    operation: str
    status_code: int
    originating_trace_id: str
    causation_depth: int
    correlation_id: str | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None

    def to_payload(self) -> JsonDict:
        """Serializes the return-leg envelope into a canonical JsonDict for InboundRecord persistence."""
        payload: JsonDict = {
            "record_id": self.source_record_id,
            "outbound_record_id": self.outbound_record_id,
            "source_record_id": self.source_record_id,
            "destination_id": self.destination_id,
            "external_id": self.destination_id,
            "connection_id": self.connection_id,
            "app_id": self.app_id,
            "stream_name": self.stream_name,
            "operation": self.operation,
            "status_code": self.status_code,
            "originating_trace_id": self.originating_trace_id,
            "causation_depth": self.causation_depth,
            "correlation_id": self.correlation_id,
            "response_body": self.response_body,
            "response_s3_key": self.response_s3_key,
        }
        return payload


__all__ = ["ResponseEventEnvelope"]
