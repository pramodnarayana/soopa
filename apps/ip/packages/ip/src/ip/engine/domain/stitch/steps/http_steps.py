"""Strongly-typed DTOs for HTTP Mutation and Dispatch Stitch steps."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundConflictStrategy,
)
from ip.engine.domain.exceptions import CodecError, IpError, Result
from ip.engine.domain.stitch.steps.common import resolve_effective_payload


@dataclass(frozen=True, kw_only=True)
class ExecuteHttpActionStepInput:
    """Strongly-typed input DTO for dispatching an L5 outbound mutation from a Stitch step."""

    connection_id: str
    stream_name: str
    operation: str = HttpWriteOperation.CREATE.value
    payload: JsonDict = field(default_factory=dict)
    record_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL
    causation_depth: int = 0
    mapping_spec_id: str | None = None

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[ExecuteHttpActionStepInput, IpError]:
        effective_data = resolve_effective_payload(data)
        conn_id = (
            effective_data.get("destination_connection_id")
            or effective_data.get("target_connection_id")
            or effective_data.get("connection_id")
        )
        stream_name = (
            effective_data.get("destination_stream")
            or effective_data.get("stream_name")
            or effective_data.get("stream")
        )
        raw_op = effective_data.get("operation", HttpWriteOperation.CREATE.value)
        if "payload" in effective_data:
            raw_payload = effective_data["payload"]
        else:
            raw_payload = {k: v for k, v in effective_data.items() if k != "parents"}
        raw_record_id = (
            effective_data["record_id"]
            if "record_id" in effective_data and effective_data["record_id"] is not None
            else effective_data.get("source_id")
        )
        raw_headers = effective_data.get("headers")
        raw_conflict = effective_data.get("conflict_strategy", OutboundConflictStrategy.FAIL.value)
        raw_causation_depth = effective_data.get("causation_depth", 0)
        raw_mapping_spec_id = effective_data.get("mapping_spec_id")

        if (
            not isinstance(conn_id, str)
            or not conn_id.strip()
            or not isinstance(stream_name, str)
            or not stream_name.strip()
            or not isinstance(raw_op, str)
            or not raw_op.strip()
        ):
            return Result.err(
                CodecError.with_message(
                    "ExecuteHttpActionStepInput requires non-empty connection_id, "
                    "stream_name, and operation."
                )
            )

        op_str = raw_op.strip().upper()
        try:
            validated_op = HttpWriteOperation(op_str)
        except ValueError:
            return Result.err(
                CodecError.with_message(
                    f"Unsupported HTTP write operation '{raw_op}' for ExecuteHttpActionStepInput"
                )
            )

        payload_dict: JsonDict = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        headers_dict: dict[str, str] = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )
        try:
            conflict_strat = OutboundConflictStrategy(str(raw_conflict))
        except ValueError:
            conflict_strat = OutboundConflictStrategy.FAIL

        if isinstance(raw_causation_depth, int) and not isinstance(raw_causation_depth, bool):
            if raw_causation_depth < 0:
                return Result.err(
                    CodecError.with_message(
                        f"causation_depth cannot be negative, got {raw_causation_depth}"
                    )
                )
            resolved_depth = raw_causation_depth
        else:
            resolved_depth = 0

        return Result.ok(
            cls(
                connection_id=conn_id.strip(),
                stream_name=stream_name.strip(),
                operation=validated_op.value,
                payload=payload_dict,
                record_id=str(raw_record_id).strip()
                if isinstance(raw_record_id, (str, int)) and str(raw_record_id).strip()
                else None,
                headers=headers_dict,
                conflict_strategy=conflict_strat,
                causation_depth=resolved_depth,
                mapping_spec_id=str(raw_mapping_spec_id).strip()
                if isinstance(raw_mapping_spec_id, str) and str(raw_mapping_spec_id).strip()
                else None,
            )
        )


@dataclass(frozen=True, kw_only=True)
class ExecuteHttpActionStepOutput:
    """Strongly-typed output DTO returned after an L5 outbound dispatch completes."""

    outbound_record_id: str
    status: str
    record_id: str
    destination_id: str | None = None
    response_status_code: int | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    was_deduplicated: bool = False
    was_token_refreshed: bool = False

    def to_payload(self) -> JsonDict:
        return {
            "outbound_record_id": self.outbound_record_id,
            "status": self.status,
            "record_id": self.record_id,
            "destination_id": self.destination_id,
            "response_status_code": self.response_status_code,
            "response_body": dict(self.response_body) if self.response_body is not None else None,
            "response_s3_key": self.response_s3_key,
            "was_deduplicated": self.was_deduplicated,
            "was_token_refreshed": self.was_token_refreshed,
        }


@dataclass(frozen=True, kw_only=True)
class HttpDispatchStepInput:
    """Strongly-typed input DTO for dispatching HTTP requests via Solution SDK ConnectorSpec."""

    connection_id: str
    app: str
    entity: str
    command_payload: JsonDict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[HttpDispatchStepInput, IpError]:
        effective = resolve_effective_payload(data)
        conn_id = effective.get("connection_id") or effective.get("source_connection_id")
        app = effective.get("app") or effective.get("source_app")
        entity = (
            effective.get("entity") or effective.get("source_entity") or effective.get("stream")
        )
        if not isinstance(conn_id, str) or not conn_id.strip():
            return Result.err(
                CodecError.with_message("HttpDispatchStepInput requires a valid connection_id.")
            )
        if not isinstance(app, str) or not app.strip():
            return Result.err(
                CodecError.with_message("HttpDispatchStepInput requires a valid app identifier.")
            )
        if not isinstance(entity, str) or not entity.strip():
            return Result.err(
                CodecError.with_message("HttpDispatchStepInput requires a valid entity identifier.")
            )
        raw_cmd = effective.get("command_payload") or effective.get("command") or effective
        cmd_dict: dict[str, JsonValue] = (
            {
                k: v
                for k, v in raw_cmd.items()
                if k not in ("parents", "connection_id", "app", "entity")
            }
            if isinstance(raw_cmd, dict)
            else {}
        )
        return Result.ok(
            cls(
                connection_id=conn_id.strip(),
                app=app.strip(),
                entity=entity.strip(),
                command_payload=cmd_dict,
            )
        )


@dataclass(frozen=True, kw_only=True)
class HttpDispatchStepOutput:
    """Output DTO returned after HTTP dispatch against the external service."""

    connection_id: str
    app: str
    entity: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    raw_payload: str = ""

    def to_payload(self) -> JsonDict:
        return {
            "connection_id": self.connection_id,
            "app": self.app,
            "entity": self.entity,
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[HttpDispatchStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        raw_status = effective.get("status_code", 0)
        status_code = int(raw_status) if isinstance(raw_status, (int, float, str)) else 0
        raw_headers = effective.get("headers")
        headers = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )
        return Result.ok(
            cls(
                connection_id=str(effective.get("connection_id", "")),
                app=str(effective.get("app", "")),
                entity=str(effective.get("entity", "")),
                status_code=status_code,
                headers=headers,
                raw_payload=str(effective.get("raw_payload", "")),
            )
        )


__all__ = [
    "ExecuteHttpActionStepInput",
    "ExecuteHttpActionStepOutput",
    "HttpDispatchStepInput",
    "HttpDispatchStepOutput",
]
