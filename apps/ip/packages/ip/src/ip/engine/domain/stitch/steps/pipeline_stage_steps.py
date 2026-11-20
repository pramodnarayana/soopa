"""Strongly-typed DTOs for Pipeline Stage Stitch steps (L1, L2, Normalizer, UI Mapper, Egress)."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import CodecError, IpError, Result
from ip.engine.domain.stitch.steps.common import resolve_effective_payload


@dataclass(frozen=True, kw_only=True)
class L1PersistStepInput:
    """Strongly-typed input DTO for persisting raw wire bytes to L1 immutable storage."""

    connection_id: str
    app: str
    entity: str
    raw_payload: str

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[L1PersistStepInput, IpError]:
        effective = resolve_effective_payload(data)
        conn_id = effective.get("connection_id", "")
        app = effective.get("app", "")
        entity = effective.get("entity", "")
        raw = effective.get("raw_payload", "")
        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else ""
        return Result.ok(
            cls(
                connection_id=str(conn_id),
                app=str(app),
                entity=str(entity),
                raw_payload=raw,
            )
        )


@dataclass(frozen=True, kw_only=True)
class L1PersistStepOutput:
    """Output DTO returned after storing raw payload into L1 tiered storage."""

    connection_id: str
    app: str
    entity: str
    sha256: str
    s3_key: str | None
    is_inlined: bool
    raw_payload: str

    def to_payload(self) -> JsonDict:
        return {
            "connection_id": self.connection_id,
            "app": self.app,
            "entity": self.entity,
            "sha256": self.sha256,
            "s3_key": self.s3_key,
            "is_inlined": self.is_inlined,
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[L1PersistStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        return Result.ok(
            cls(
                connection_id=str(effective.get("connection_id", "")),
                app=str(effective.get("app", "")),
                entity=str(effective.get("entity", "")),
                sha256=str(effective.get("sha256", "")),
                s3_key=str(effective["s3_key"]) if effective.get("s3_key") is not None else None,
                is_inlined=bool(effective.get("is_inlined", True)),
                raw_payload=str(effective.get("raw_payload", "")),
            )
        )


@dataclass(frozen=True, kw_only=True)
class L2ReplicaStepInput:
    """Strongly-typed input DTO for replicating records into the L2 relational query store."""

    connection_id: str
    app: str
    entity: str
    raw_payload: str

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[L2ReplicaStepInput, IpError]:
        effective = resolve_effective_payload(data)
        return Result.ok(
            cls(
                connection_id=str(effective.get("connection_id", "")),
                app=str(effective.get("app", "")),
                entity=str(effective.get("entity", "")),
                raw_payload=str(effective.get("raw_payload", "")),
            )
        )


@dataclass(frozen=True, kw_only=True)
class L2ReplicaStepOutput:
    """Output DTO returned after replicating records into L2."""

    connection_id: str
    app: str
    entity: str
    replicated_count: int
    raw_payload: str

    def to_payload(self) -> JsonDict:
        return {
            "connection_id": self.connection_id,
            "app": self.app,
            "entity": self.entity,
            "replicated_count": self.replicated_count,
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[L2ReplicaStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        raw_count = effective.get("replicated_count", 0)
        count = int(raw_count) if isinstance(raw_count, (int, float, str)) else 0
        return Result.ok(
            cls(
                connection_id=str(effective.get("connection_id", "")),
                app=str(effective.get("app", "")),
                entity=str(effective.get("entity", "")),
                replicated_count=count,
                raw_payload=str(effective.get("raw_payload", "")),
            )
        )


@dataclass(frozen=True, kw_only=True)
class NormalizerStepInput:
    """Strongly-typed input DTO for executing pure domain transformation via Solution SDK."""

    app: str
    entity: str
    raw_payload: str
    connection_id: str = ""

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[NormalizerStepInput, IpError]:
        effective = resolve_effective_payload(data)
        app = effective.get("app", "")
        entity = effective.get("entity", "")
        raw = effective.get("raw_payload", "")
        if not isinstance(app, str) or not app.strip():
            return Result.err(
                CodecError.with_message("NormalizerStepInput requires a valid app identifier.")
            )
        if not isinstance(entity, str) or not entity.strip():
            return Result.err(
                CodecError.with_message("NormalizerStepInput requires a valid entity identifier.")
            )
        return Result.ok(
            cls(
                app=app.strip(),
                entity=entity.strip(),
                raw_payload=str(raw) if raw is not None else "",
                connection_id=str(effective.get("connection_id", "")),
            )
        )


@dataclass(frozen=True, kw_only=True)
class NormalizerStepOutput:
    """Output DTO returning canonical domain events produced by the Solution TransformerSpec."""

    app: str
    entity: str
    connection_id: str
    normalized_records: tuple[JsonDict, ...]

    def to_payload(self) -> JsonDict:
        return {
            "app": self.app,
            "entity": self.entity,
            "connection_id": self.connection_id,
            "normalized_records": [dict(r) for r in self.normalized_records],
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[NormalizerStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        raw_recs = effective.get("normalized_records") or ()
        records: list[JsonDict] = []
        if isinstance(raw_recs, (list, tuple)):
            for r in raw_recs:
                if isinstance(r, dict):
                    records.append(r)
        return Result.ok(
            cls(
                app=str(effective.get("app", "")),
                entity=str(effective.get("entity", "")),
                connection_id=str(effective.get("connection_id", "")),
                normalized_records=tuple(records),
            )
        )


@dataclass(frozen=True, kw_only=True)
class UiFieldMapperStepInput:
    """Strongly-typed input DTO for applying declarative Field Mapping Specs to canonical records."""

    mapping_spec_id: str | None
    records: tuple[JsonDict, ...]

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[UiFieldMapperStepInput, IpError]:
        effective = resolve_effective_payload(data)
        raw_spec_id = effective.get("mapping_spec_id")
        raw_records = effective.get("normalized_records") or effective.get("records") or ()
        records: list[JsonDict] = []
        if isinstance(raw_records, (list, tuple)):
            for item in raw_records:
                if isinstance(item, dict):
                    records.append(item)
        return Result.ok(
            cls(
                mapping_spec_id=str(raw_spec_id) if raw_spec_id else None,
                records=tuple(records),
            )
        )


@dataclass(frozen=True, kw_only=True)
class UiFieldMapperStepOutput:
    """Output DTO returning projected wire contracts."""

    projected_records: tuple[JsonDict, ...]

    def to_payload(self) -> JsonDict:
        return {
            "projected_records": [dict(r) for r in self.projected_records],
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[UiFieldMapperStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        raw_recs = effective.get("projected_records") or ()
        records: list[JsonDict] = []
        if isinstance(raw_recs, (list, tuple)):
            for r in raw_recs:
                if isinstance(r, dict):
                    records.append(r)
        return Result.ok(
            cls(
                projected_records=tuple(records),
            )
        )


@dataclass(frozen=True, kw_only=True)
class EgressPublishStepInput:
    """Strongly-typed input DTO for publishing mapped records to the destination Kafka topic."""

    destination_topic: str
    destination_partition_key_field: str = "id"
    records: tuple[JsonDict, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[EgressPublishStepInput, IpError]:
        effective = resolve_effective_payload(data)
        topic = (
            effective.get("destination_topic") or effective.get("topic") or "default_egress_topic"
        )
        key_field = effective.get("destination_partition_key_field") or "id"
        raw_recs = effective.get("projected_records") or effective.get("records") or ()
        records: list[JsonDict] = []
        if isinstance(raw_recs, (list, tuple)):
            for r in raw_recs:
                if isinstance(r, dict):
                    records.append(r)
        return Result.ok(
            cls(
                destination_topic=str(topic),
                destination_partition_key_field=str(key_field),
                records=tuple(records),
            )
        )


@dataclass(frozen=True, kw_only=True)
class EgressPublishStepOutput:
    """Output DTO returned after publishing records to the egress transport."""

    published_count: int
    destination_topic: str

    def to_payload(self) -> JsonDict:
        return {
            "published_count": self.published_count,
            "destination_topic": self.destination_topic,
        }

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[EgressPublishStepOutput, IpError]:
        effective = resolve_effective_payload(data)
        raw_count = effective.get("published_count", 0)
        count = int(raw_count) if isinstance(raw_count, (int, float, str)) else 0
        return Result.ok(
            cls(
                published_count=count,
                destination_topic=str(effective.get("destination_topic", "")),
            )
        )


__all__ = [
    "EgressPublishStepInput",
    "EgressPublishStepOutput",
    "L1PersistStepInput",
    "L1PersistStepOutput",
    "L2ReplicaStepInput",
    "L2ReplicaStepOutput",
    "NormalizerStepInput",
    "NormalizerStepOutput",
    "UiFieldMapperStepInput",
    "UiFieldMapperStepOutput",
]
