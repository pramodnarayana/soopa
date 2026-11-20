"""Strongly-typed DTOs for QueryReplica Stitch steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import CodecError, IpError, Result


@dataclass(frozen=True, kw_only=True)
class QueryReplicaStepInput:
    """Strongly-typed input DTO for querying an L2 ReplicaRecord inside a Stitch step."""

    connection_id: str
    stream: str
    record_key: str

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[QueryReplicaStepInput, IpError]:
        conn_id = data.get("connection_id") or data.get("source_connection_id")
        stream = data.get("stream") or data.get("stream_name")
        rec_key = data.get("record_key") or data.get("source_id")
        if (
            not isinstance(conn_id, str)
            or not conn_id.strip()
            or not isinstance(stream, str)
            or not stream.strip()
            or not isinstance(rec_key, str)
            or not rec_key.strip()
        ):
            return Result.err(
                CodecError.with_message(
                    "QueryReplicaStepInput requires non-empty string connection_id, stream, and record_key."
                )
            )
        return Result.ok(
            cls(
                connection_id=conn_id,
                stream=stream,
                record_key=rec_key,
            )
        )


@dataclass(frozen=True, kw_only=True)
class QueryReplicaStepOutput:
    """Strongly-typed output DTO from querying an L2 ReplicaRecord."""

    found: bool
    record_id: str | None = None
    version: int | None = None
    data: JsonDict = field(default_factory=dict)

    def to_payload(self) -> JsonDict:
        return {
            "found": self.found,
            "record_id": self.record_id,
            "version": self.version,
            "data": dict(self.data),
        }


__all__ = [
    "QueryReplicaStepInput",
    "QueryReplicaStepOutput",
]
