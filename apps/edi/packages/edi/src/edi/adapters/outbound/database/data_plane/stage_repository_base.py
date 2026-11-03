from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar, cast

import structlog
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.elements import ColumnElement
from strace.domain import TracedAggregateRoot

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from database.types import TenantSession
from edi.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, TraceEvent
from edi.adapters.outbound.database.models.data_plane import EdiJson as OrmEdiJson
from edi.adapters.outbound.database.models.data_plane import EdiMessage as OrmEdiMessage
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiOutboxSource
from edi.domain.transaction.stage_filter import (
    ALLOWED_STAGE_FILTER_FIELDS,
    EDI_JSON_UNSUPPORTED_FILTER_FIELDS,
    FilterOperator,
    StageFilterCriterion,
)
from edi.ports.outbound.storage_port import StoragePort

logger = structlog.get_logger(__name__)

_StageOrmT = TypeVar("_StageOrmT", OrmEdiMessage, OrmEdiJson)


def event_idempotency_key(idempotency_key: str | None, *, index: int, event_count: int) -> str:
    base_key = idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY)
    return f"{base_key}_{index}" if event_count > 1 else base_key


class DataPlaneStageSqlAlchemyRepository(TenantSqlAlchemyRepository):
    """Shared base repository for EDI Data-Plane stage aggregates (EdiMessage, EdiJson)."""

    def __init__(self, session: TenantSession, storage: StoragePort) -> None:
        super().__init__(session)
        self.storage = storage

    async def _persist_trace_events(self, aggregate: TracedAggregateRoot) -> None:
        for t_event in aggregate.trace_events:
            try:
                async with self.session.begin_nested():
                    trace_record = TraceEvent(
                        id=t_event.id,
                        tenant_id=t_event.tenant_id,
                        trace_id=t_event.trace_id,
                        event_type=t_event.event_type,
                        actor=t_event.actor,
                        metadata_=t_event.metadata,
                    )
                    self.session.add(trace_record)
                    await self.flush()
            except DuplicateEntityError:
                logger.info(
                    "edi_stage_trace_event_deduplicated",
                    trace_event_id=t_event.id,
                    trace_id=t_event.trace_id,
                    event_type=t_event.event_type,
                )
        aggregate.clear_trace_events()

    async def _drain_stage_events(self, aggregate: TracedAggregateRoot) -> list[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        event_count = len(aggregate.domain_events)
        for index, event in enumerate(aggregate.domain_events):
            event_id = generate_id(DomainIdPrefix.EDI_DP_OUTBOX.value)
            idempotency_key = event_idempotency_key(
                event.idempotency_key,
                index=index,
                event_count=event_count,
            )
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or aggregate.tenant_id
            outbox_record = DataPlaneOutbox(
                id=event_id,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                event_type=event.event_name,
                payload=payload_dict,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(outbox_record)
                    await self.flush()
                envelopes.append(
                    EventEnvelope(
                        id=event_id,
                        source=EdiOutboxSource.EDI_DATA_PLANE,
                        tenant_id=tenant_id,
                        event_type=event.event_name,
                        payload=payload_dict,
                        idempotency_key=idempotency_key,
                    )
                )
            except DuplicateEntityError:
                logger.info(
                    "edi_stage_outbox_event_deduplicated",
                    idempotency_key=idempotency_key,
                    event_type=event.event_name,
                    tenant_id=tenant_id,
                )

        await self._persist_trace_events(aggregate)
        aggregate.clear_domain_events()
        return envelopes

    def _apply_dynamic_filters(
        self,
        stmt: Select[tuple[_StageOrmT]],
        model: type[_StageOrmT],
        filters: Sequence[StageFilterCriterion],
    ) -> Select[tuple[_StageOrmT]]:
        for criterion in filters:
            field = criterion.field
            operator = criterion.operator
            value = criterion.value
            if value is None or field not in ALLOWED_STAGE_FILTER_FIELDS:
                continue

            if issubclass(model, OrmEdiJson) and field in EDI_JSON_UNSUPPORTED_FILTER_FIELDS:
                continue

            if field == "trading_partner_id":
                if issubclass(model, OrmEdiMessage):
                    cond_cols = [
                        model.sender_id,
                        model.receiver_id,
                        model.gs_sender_id,
                        model.gs_receiver_id,
                        model.trading_partner_id,
                    ]
                else:
                    cond_cols = [model.trading_partner_id]

                if operator == FilterOperator.EQ:
                    stmt = stmt.where(or_(*(col == str(value) for col in cond_cols)))
                elif operator == FilterOperator.NEQ:
                    stmt = stmt.where(
                        and_(*(or_(col.is_(None), col != str(value)) for col in cond_cols))
                    )
                elif operator == FilterOperator.CONTAINS:
                    escaped_value = (
                        str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    )
                    pattern = f"%{escaped_value}%"
                    stmt = stmt.where(or_(*(col.ilike(pattern, escape="\\") for col in cond_cols)))
                elif operator == FilterOperator.IN and isinstance(value, list):
                    stmt = stmt.where(or_(*(col.in_(value) for col in cond_cols)))
                continue

            if field.startswith("business_metadata.") and issubclass(model, OrmEdiJson):
                json_key = field.split("business_metadata.")[1]
                column = model.business_metadata[json_key]
                column_astext = column.astext
                if operator == FilterOperator.EQ:
                    stmt = stmt.where(
                        or_(
                            column_astext == str(value),
                            model.business_metadata.contains({json_key: value}),
                            model.business_metadata.contains({json_key: [value]}),
                        )
                    )
                elif operator == FilterOperator.NEQ:
                    stmt = stmt.where(
                        and_(
                            column_astext != str(value),
                            ~model.business_metadata.contains({json_key: value}),
                            ~model.business_metadata.contains({json_key: [value]}),
                        )
                    )
                elif operator == FilterOperator.CONTAINS:
                    escaped_value = (
                        str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    )
                    stmt = stmt.where(column_astext.ilike(f"%{escaped_value}%", escape="\\"))
                elif operator == FilterOperator.IN and isinstance(value, list):
                    json_conds = [column_astext.in_([str(v) for v in value])]
                    for v in value:
                        json_conds.append(model.business_metadata.contains({json_key: v}))
                        json_conds.append(model.business_metadata.contains({json_key: [v]}))
                    stmt = stmt.where(or_(*json_conds))
                continue

            attr: Mapped[object] | None = None
            if field == "trace_id":
                attr = model.trace_id
            elif field == "parent_trace_id":
                attr = model.parent_trace_id
            elif field == "original_trace_id":
                attr = model.original_trace_id
            elif field == "direction":
                attr = model.direction
            elif field == "status":
                attr = model.status
            elif field == "transaction_type":
                attr = model.transaction_type
            elif field == "error_code":
                attr = model.error_code
            elif field == "status_message":
                attr = model.status_message
            elif field == "sender_id" and issubclass(model, OrmEdiMessage):
                attr = model.sender_id
            elif field == "receiver_id" and issubclass(model, OrmEdiMessage):
                attr = model.receiver_id
            elif field == "gs_sender_id" and issubclass(model, OrmEdiMessage):
                attr = model.gs_sender_id
            elif field == "gs_receiver_id" and issubclass(model, OrmEdiMessage):
                attr = model.gs_receiver_id
            elif field == "format_standard" and issubclass(model, OrmEdiMessage):
                attr = model.format_standard
            elif field == "connection_type" and issubclass(model, OrmEdiMessage):
                attr = model.connection_type

            if attr is None:
                continue

            if operator == FilterOperator.EQ:
                stmt = stmt.where(attr == value)
            elif operator == FilterOperator.NEQ:
                stmt = stmt.where(attr != value)
            elif operator == FilterOperator.CONTAINS:
                escaped_value = (
                    str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                stmt = stmt.where(
                    cast(ColumnElement[bool], attr.ilike(f"%{escaped_value}%", escape="\\"))
                )
            elif operator == FilterOperator.IN and isinstance(value, list):
                stmt = stmt.where(attr.in_(value))

        return stmt
