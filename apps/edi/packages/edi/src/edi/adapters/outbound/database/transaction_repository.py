import json
import os
from collections.abc import Sequence
from typing import Any, Protocol, cast


class RouteModelProtocol(Protocol):
    gs_sender_id: str | None
    gs_receiver_id: str | None
    trading_partner_id: str | None


from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonValue
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import DeclarativeBase

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from edi.adapters.outbound.database.base_repository import TenantSession, TenantSqlAlchemyRepository
from edi.adapters.outbound.database.constants import (
    API_GATEWAY_ID_PREFIX,
    DATA_PLANE_OUTBOX_EVENT_PREFIX,
    EDI_JSON_ID_PREFIX,
)
from edi.adapters.outbound.database.models.control_plane import OutboundEdiHeader
from edi.adapters.outbound.database.models.data_plane import (
    ApiGateway,
    DataPlaneOutbox,
    EdiJson,
    EdiMessage,
    InboundRoute,
    OutboundRoute,
    Webhook,
)
from edi.adapters.outbound.database.payload_hydration import (
    hydrate_edi_data,
    hydrate_json_payload,
)
from edi.application.dtos.routes import InboundRouteDTO
from edi.application.dtos.transactions import (
    EdiJsonDTO,
    EdiMessageDTO,
)
from edi.application.dtos.webhooks import WebhookDTO
from edi.domain.constants import EDI_MESSAGE_ID_PREFIX
from edi.domain.enums import EdiDirection
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort


class SqlAlchemyTransactionRepository(TransactionRepositoryPort, TenantSqlAlchemyRepository):
    def __init__(self, session: TenantSession, storage: StoragePort) -> None:
        TenantSqlAlchemyRepository.__init__(self, session)
        self.storage = storage

    async def create_edi_message(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{EDI_MESSAGE_ID_PREFIX}_{os.urandom(12).hex()}"
        msg = EdiMessage(tenant_id=tenant_id, **payload_copy)
        self.session.add(msg)
        await self.flush()
        return str(msg.id)

    async def publish_outbox_event(
        self, tenant_id: str, event_type: str, payload: JsonValue, idempotency_key: str | None
    ) -> str:
        serialized_payload = (
            serialize_domain_event(payload) if not isinstance(payload, dict) else payload
        )

        event_id = f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}_{os.urandom(12).hex()}"
        record = DataPlaneOutbox(
            id=event_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            payload=serialized_payload,
            status=OutboxStatus.PENDING,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.flush()
                return str(event_id)
        except DuplicateEntityError:
            return ""

    async def save(self, aggregate: EdiMessageDomainModel) -> None:
        """
        Drains domain events from the aggregate into the outbox table within
        the same open transaction. This is the DDD-compliant publishing mechanism.
        """
        # Save aggregate state
        record_id = (
            aggregate.id if aggregate.id else f"{EDI_MESSAGE_ID_PREFIX}_{os.urandom(12).hex()}"
        )
        record = EdiMessage(
            id=record_id,
            trace_id=aggregate.trace_id,
            tenant_id=aggregate.tenant_id,
            direction=aggregate.direction.value if aggregate.direction else None,
            status=aggregate.status.value if aggregate.status else None,
            format_standard=aggregate.format_standard,
            transaction_type=aggregate.transaction_type,
            connection_type=aggregate.connection_type,
            sender_id=aggregate.sender_id,
            receiver_id=aggregate.receiver_id,
            gs_sender_id=aggregate.gs_sender_id,
            gs_receiver_id=aggregate.gs_receiver_id,
            edi_data=aggregate.edi_data,
            trading_partner_id=aggregate.trading_partner_id,
            storage_uri=aggregate.storage_uri,
        )
        await self.session.merge(record)

        for index, event in enumerate(aggregate.domain_events):
            event_id = f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}_{os.urandom(12).hex()}"
            idempotency_key = (
                f"{event.idempotency_key}_{index}"
                if len(aggregate.domain_events) > 1
                else event.idempotency_key
            )
            payload_dict = serialize_domain_event(event)
            outbox_record = DataPlaneOutbox(
                id=event_id,
                tenant_id=event.get_routing_tenant_id() or aggregate.tenant_id,
                idempotency_key=idempotency_key,
                event_type=event.event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(outbox_record)
                    await self.flush()
            except DuplicateEntityError:
                pass  # Idempotent: already published, safe to skip.

        aggregate.clear_domain_events()

    async def save_json(self, aggregate: EdiJsonDomainModel) -> None:
        """
        Drains domain events from the EdiJson aggregate into the outbox table within
        the same open transaction.
        """
        # Save aggregate state
        record_id = aggregate.id if aggregate.id else f"{EDI_JSON_ID_PREFIX}_{os.urandom(12).hex()}"
        record = EdiJson(
            id=record_id,
            trace_id=aggregate.trace_id,
            tenant_id=aggregate.tenant_id,
            direction=aggregate.direction.value if aggregate.direction else None,
            status=aggregate.status.value if aggregate.status else None,
            trading_partner_id=aggregate.trading_partner_id,
            transaction_type=aggregate.transaction_type,
            standard=aggregate.standard,
            sender_id=aggregate.sender_id,
            receiver_id=aggregate.receiver_id,
            gs_sender_id=aggregate.gs_sender_id,
            gs_receiver_id=aggregate.gs_receiver_id,
            business_metadata=aggregate.business_metadata,
            payload=aggregate.payload,
        )
        await self.session.merge(record)

        for index, event in enumerate(aggregate.domain_events):
            event_id = f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}_{os.urandom(12).hex()}"
            idempotency_key = (
                f"{event.idempotency_key}_{index}"
                if len(aggregate.domain_events) > 1
                else event.idempotency_key
            )
            payload_dict = serialize_domain_event(event)
            outbox_record = DataPlaneOutbox(
                id=event_id,
                tenant_id=event.get_routing_tenant_id() or aggregate.tenant_id,
                idempotency_key=idempotency_key,
                event_type=event.event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(outbox_record)
                    await self.flush()
            except DuplicateEntityError:
                pass  # Idempotent: already published, safe to skip.

        aggregate.clear_domain_events()

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        stmt = (
            select(EdiMessage)
            .where(EdiMessage.trace_id == str(trace_id))
            .order_by(EdiMessage.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return _map_edi_message_to_domain(record)

    async def get_route(
        self, direction: str, sender_id: str, receiver_id: str, transaction_type: str
    ) -> InboundRouteDTO | None:
        stmt: Select[tuple[Any, ...]] | None = None
        if direction == EdiDirection.INBOUND:
            stmt = select(InboundRoute).where(
                InboundRoute.isa_sender_id == sender_id,
                InboundRoute.isa_receiver_id == receiver_id,
                or_(
                    InboundRoute.transaction_type == transaction_type,
                    InboundRoute.transaction_type.is_(None),
                ),
            )
        else:
            stmt = (
                select(OutboundRoute)
                .join(
                    OutboundEdiHeader,
                    OutboundRoute.trading_partner_id == OutboundEdiHeader.trading_partner_id,
                )
                .where(
                    OutboundEdiHeader.isa_sender_id == sender_id,
                    OutboundEdiHeader.isa_receiver_id == receiver_id,
                    or_(
                        OutboundEdiHeader.transaction_type == transaction_type,
                        OutboundEdiHeader.transaction_type.is_(None),
                    ),
                )
            )

        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if not record:
            return None
        return InboundRouteDTO(
            trading_partner_id=record.trading_partner_id,
            webhook_id=record.webhook_id,
            as2_partner_id=getattr(record, "as2_partner_id", None),
            sftp_partner_id=record.sftp_partner_id,
            processing_mode=record.processing_mode,
        )

    async def get_webhook(self, partner_id: str) -> WebhookDTO | None:
        stmt = select(Webhook).where(Webhook.id == partner_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return WebhookDTO(
            id=str(record.id),
            url=str(record.url),
            name=str(record.name),
            active=bool(record.active),
            auth_header_vault_ref=record.auth_header_vault_ref,
        )

    async def save_api_payload(
        self,
        trace_id: str,
        direction: str,
        payload: dict[str, JsonValue],
        status: str,
        transaction_type: str | None = None,
        webhook_url: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        record_id = f"{API_GATEWAY_ID_PREFIX}_{os.urandom(12).hex()}"
        record = ApiGateway(
            id=record_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=direction,
            payload=payload,
            status=status,
            transaction_type=transaction_type,
            webhook_url=webhook_url,
        )
        self.session.add(record)
        await self.flush()

    async def save_edi_json(
        self,
        trace_id: str,
        direction: str,
        partnership_id: str | None,
        transaction_type: str | None,
        standard: str | None,
        sender_id: str | None,
        receiver_id: str | None,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        business_metadata: dict[str, JsonValue],
        payload: dict[str, JsonValue],
        status: str,
        tenant_id: str | None = None,
    ) -> str:
        # Idempotency check
        stmt = (
            select(EdiJson.id)
            .where(
                EdiJson.trace_id == str(trace_id),
                EdiJson.direction == direction,
                EdiJson.transaction_type == transaction_type,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        existing_id = result.scalar_one_or_none()
        if existing_id:
            return str(existing_id)

        record_id = f"{EDI_JSON_ID_PREFIX}_{os.urandom(12).hex()}"
        record = EdiJson(
            id=record_id,
            trace_id=str(trace_id),
            tenant_id=tenant_id,
            direction=direction,
            trading_partner_id=partnership_id,
            transaction_type=transaction_type,
            standard=standard,
            sender_id=sender_id,
            receiver_id=receiver_id,
            gs_sender_id=gs_sender_id,
            gs_receiver_id=gs_receiver_id,
            business_metadata=business_metadata,
            payload=payload,
            status=status,
        )
        self.session.add(record)
        await self.flush()
        return record_id

    async def create_edi_json(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{EDI_JSON_ID_PREFIX}_{os.urandom(12).hex()}"
        msg = EdiJson(tenant_id=tenant_id, **payload_copy)
        self.session.add(msg)
        await self.flush()
        return str(msg.id)

    async def create_api_gateway(self, tenant_id: str, payload: dict[str, JsonValue]) -> str:
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{API_GATEWAY_ID_PREFIX}_{os.urandom(12).hex()}"
        log = ApiGateway(tenant_id=tenant_id, **payload_copy)
        self.session.add(log)
        await self.flush()
        return str(log.id)

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessageDTO]:

        limit = min(max(1, limit), 200)
        offset = max(0, offset)

        tid_str = tenant_id if tenant_id is not None else None
        stmt = select(EdiMessage).where(EdiMessage.tenant_id == tid_str)
        if direction:
            stmt = stmt.where(EdiMessage.direction == direction)
        if transaction_type:
            stmt = stmt.where(EdiMessage.transaction_type == transaction_type)
        if partner_id:
            stmt = stmt.where(
                or_(
                    EdiMessage.sender_id == partner_id,
                    EdiMessage.receiver_id == partner_id,
                    EdiMessage.gs_sender_id == partner_id,
                    EdiMessage.gs_receiver_id == partner_id,
                )
            )
        stmt = stmt.order_by(EdiMessage.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [
            EdiMessageDTO(
                id=str(r.id),
                trace_id=str(r.trace_id),
                direction=r.direction,
                connection_type=r.connection_type,
                sender_id=r.sender_id,
                receiver_id=r.receiver_id,
                as2_sender_id=r.as2_sender_id,
                as2_receiver_id=r.as2_receiver_id,
                gs_sender_id=r.gs_sender_id,
                gs_receiver_id=r.gs_receiver_id,
                message_id=r.message_id,
                mdn_id=r.mdn_id,
                mdn_mode=r.mdn_mode,
                mdn_response=r.mdn_response,
                file_name=r.file_name,
                content_type=r.content_type,
                signature_algorithm=r.signature_algorithm,
                encryption_algorithm=r.encryption_algorithm,
                trading_partner_id=r.trading_partner_id,
                status=r.status,
                edi_data=await hydrate_edi_data(self.storage, r.storage_uri, r.edi_data),
                interchange_control_no=r.interchange_control_no,
                transaction_type=r.transaction_type,
                format_standard=r.format_standard,
                storage_uri=r.storage_uri,
                file_size_bytes=r.file_size_bytes,
                msg_headers=json.loads(r.msg_headers) if r.msg_headers else None,
                state=r.state,
                status_message=r.status_message,
                is_resend=r.is_resend,
                parent_trace_id=r.parent_trace_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in result.scalars().all()
        ]

    # Allowed filter fields and operators — whitelist to prevent arbitrary column access.
    _ALLOWED_OPERATORS: frozenset[str] = frozenset({"eq", "neq", "contains", "in"})
    _ALLOWED_FIELDS: frozenset[str] = frozenset(
        {
            "trading_partner_id",
            "direction",
            "status",
            "transaction_type",
            "sender_id",
            "receiver_id",
            "gs_sender_id",
            "gs_receiver_id",
            "format_standard",
            "connection_type",
            "business_metadata.shipment_id",
            "business_metadata.purchase_order_id",
            "business_metadata.po_number",
            "business_metadata.invoice_number",
            "business_metadata.load_number",
            "business_metadata.business_reference",
        }
    )

    def _apply_dynamic_filters(
        self,
        stmt: Select[tuple[Any, ...]],
        model: type[DeclarativeBase],
        filters: list[dict[str, JsonValue]],
    ) -> Select[tuple[Any, ...]]:

        for f in filters:
            field = f.get("field")
            operator = f.get("operator", "eq")
            value = f.get("value")
            if not field or value is None:
                continue

            # Reject unknown fields and operators
            if field not in self._ALLOWED_FIELDS or operator not in self._ALLOWED_OPERATORS:
                continue

            if field == "trading_partner_id":
                if hasattr(model, "sender_id") and hasattr(model, "receiver_id"):
                    has_gs = hasattr(model, "gs_sender_id") and hasattr(model, "gs_receiver_id")

                    has_tp = hasattr(model, "trading_partner_id")

                    if operator == "eq":
                        conds = [model.sender_id == value, model.receiver_id == value]
                        if has_gs:
                            conds.extend(
                                [
                                    cast(Any, model).gs_sender_id == value,
                                    cast(Any, model).gs_receiver_id == value,
                                ]
                            )
                        if has_tp:
                            conds.append(cast(Any, model).trading_partner_id == value)
                        stmt = stmt.where(or_(*conds))

                    elif operator == "neq":
                        conds = [model.sender_id != value, model.receiver_id != value]
                        if has_gs:
                            conds.extend(
                                [
                                    cast(Any, model).gs_sender_id != value,
                                    cast(Any, model).gs_receiver_id != value,
                                ]
                            )
                        if has_tp:
                            conds.append(cast(Any, model).trading_partner_id != value)
                        stmt = stmt.where(and_(*conds))

                    elif operator == "contains":
                        escaped_value = (
                            str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                        )
                        pattern = f"%{escaped_value}%"
                        conds = [
                            model.sender_id.ilike(pattern, escape="\\"),
                            model.receiver_id.ilike(pattern, escape="\\"),
                        ]
                        if has_gs:
                            conds.extend(
                                [
                                    cast(Any, model).gs_sender_id.ilike(pattern, escape="\\"),
                                    cast(Any, model).gs_receiver_id.ilike(pattern, escape="\\"),
                                ]
                            )
                        if has_tp:
                            conds.append(
                                cast(Any, model).trading_partner_id.ilike(pattern, escape="\\")
                            )
                        stmt = stmt.where(or_(*conds))

                    elif operator == "in" and isinstance(value, list):
                        conds = [model.sender_id.in_(value), model.receiver_id.in_(value)]
                        if has_gs:
                            conds.extend(
                                [
                                    cast(Any, model).gs_sender_id.in_(value),
                                    cast(Any, model).gs_receiver_id.in_(value),
                                ]
                            )
                        if has_tp:
                            conds.append(cast(Any, model).trading_partner_id.in_(value))
                        stmt = stmt.where(or_(*conds))
                continue

            if field.startswith("business_metadata.") and hasattr(model, "business_metadata"):
                json_key = field.split("business_metadata.")[1]
                column = model.business_metadata[json_key]
                column_astext = column.astext
                if operator == "eq":
                    stmt = stmt.where(
                        or_(
                            column_astext == str(value),
                            model.business_metadata.contains({json_key: value}),
                            model.business_metadata.contains({json_key: [value]}),
                        )
                    )
                elif operator == "neq":
                    stmt = stmt.where(
                        and_(
                            column_astext != str(value),
                            ~model.business_metadata.contains({json_key: value}),
                            ~model.business_metadata.contains({json_key: [value]}),
                        )
                    )
                elif operator == "contains":
                    escaped_value = (
                        str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    )
                    stmt = stmt.where(column_astext.ilike(f"%{escaped_value}%", escape="\\"))
                elif operator == "in" and isinstance(value, list):
                    conds = [column_astext.in_([str(v) for v in value])]
                    for v in value:
                        conds.append(model.business_metadata.contains({json_key: v}))
                        conds.append(model.business_metadata.contains({json_key: [v]}))
                    stmt = stmt.where(or_(*conds))
                continue

            if not hasattr(model, field):
                continue
            column = getattr(model, field)

            if operator == "eq":
                stmt = stmt.where(column == value)
            elif operator == "neq":
                stmt = stmt.where(column != value)
            elif operator == "contains":
                escaped_value = (
                    str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                stmt = stmt.where(column.ilike(f"%{escaped_value}%", escape="\\"))
            elif operator == "in" and isinstance(value, list):
                stmt = stmt.where(column.in_(value))
        return stmt

    async def explorer_list_edi_messages(
        self, tenant_id: str, filters: list[dict[str, JsonValue]], limit: int = 50, offset: int = 0
    ) -> Sequence[EdiMessageDTO]:

        tid_str = tenant_id if tenant_id is not None else None
        base_stmt = select(EdiMessage).where(EdiMessage.tenant_id == tid_str)
        stmt = cast(
            Select[tuple[EdiMessage]],
            self._apply_dynamic_filters(
                cast(Select[tuple[DeclarativeBase, ...]], base_stmt),
                cast(type[DeclarativeBase], EdiMessage),
                filters,
            ),
        )
        stmt = stmt.order_by(EdiMessage.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [
            EdiMessageDTO(
                id=str(r.id),
                trace_id=str(r.trace_id),
                direction=r.direction,
                connection_type=r.connection_type,
                sender_id=r.sender_id,
                receiver_id=r.receiver_id,
                as2_sender_id=r.as2_sender_id,
                as2_receiver_id=r.as2_receiver_id,
                gs_sender_id=r.gs_sender_id,
                gs_receiver_id=r.gs_receiver_id,
                message_id=r.message_id,
                mdn_id=r.mdn_id,
                mdn_mode=r.mdn_mode,
                mdn_response=r.mdn_response,
                file_name=r.file_name,
                content_type=r.content_type,
                signature_algorithm=r.signature_algorithm,
                encryption_algorithm=r.encryption_algorithm,
                trading_partner_id=r.trading_partner_id,
                status=r.status,
                edi_data=await hydrate_edi_data(self.storage, r.storage_uri, r.edi_data),
                interchange_control_no=r.interchange_control_no,
                transaction_type=r.transaction_type,
                format_standard=r.format_standard,
                storage_uri=r.storage_uri,
                file_size_bytes=r.file_size_bytes,
                msg_headers=json.loads(r.msg_headers) if r.msg_headers else None,
                state=r.state,
                status_message=r.status_message,
                is_resend=r.is_resend,
                parent_trace_id=r.parent_trace_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in result.scalars().all()
        ]

    async def explorer_list_edi_json(
        self, tenant_id: str, filters: list[dict[str, JsonValue]], limit: int = 50, offset: int = 0
    ) -> Sequence[EdiJsonDTO]:

        tid_str = tenant_id if tenant_id is not None else None
        base_stmt = select(EdiJson).where(EdiJson.tenant_id == tid_str)
        stmt = cast(
            Select[tuple[EdiJson]],
            self._apply_dynamic_filters(
                cast(Select[tuple[DeclarativeBase, ...]], base_stmt),
                cast(type[DeclarativeBase], EdiJson),
                filters,
            ),
        )
        stmt = stmt.order_by(EdiJson.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return [
            EdiJsonDTO(
                id=str(j.id),
                trace_id=str(j.trace_id),
                tenant_id=j.tenant_id,
                status=j.status,
                trading_partner_id=j.trading_partner_id,
                business_metadata=j.business_metadata,
                transaction_type=j.transaction_type,
                sender_id=j.sender_id,
                receiver_id=j.receiver_id,
                gs_sender_id=j.gs_sender_id,
                gs_receiver_id=j.gs_receiver_id,
                payload=await hydrate_json_payload(self.storage, j.storage_uri, j.payload),
                parent_trace_id=j.parent_trace_id,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in result.scalars().all()
        ]

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJsonDTO]:

        tid_str = tenant_id if tenant_id is not None else None
        json_stmt = (
            select(EdiJson)
            .where(EdiJson.tenant_id == tid_str, EdiJson.business_metadata.contains({key: value}))
            .order_by(EdiJson.created_at.asc())
        )

        result = await self.session.execute(json_stmt)
        return [
            EdiJsonDTO(
                id=str(r.id),
                trace_id=str(r.trace_id),
                tenant_id=r.tenant_id,
                status=r.status,
                trading_partner_id=r.trading_partner_id,
                business_metadata=r.business_metadata,
                transaction_type=r.transaction_type,
                sender_id=r.sender_id,
                receiver_id=r.receiver_id,
                gs_sender_id=r.gs_sender_id,
                gs_receiver_id=r.gs_receiver_id,
                payload=await hydrate_json_payload(self.storage, r.storage_uri, r.payload),
                parent_trace_id=r.parent_trace_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in result.scalars().all()
        ]

    async def get_existing_trace_ids(self, tenant_id: str, trace_ids: list[str]) -> set[str]:

        tid_str = tenant_id if tenant_id is not None else None

        stmt = select(EdiMessage.trace_id).where(
            EdiMessage.tenant_id == tid_str, EdiMessage.trace_id.in_(trace_ids)
        )

        result = await self.session.execute(stmt)
        return set(result.scalars().all())


def _map_edi_message_to_domain(record: EdiMessage) -> EdiMessageDomainModel:
    """
    Explicit ORM → Domain mapper for EdiMessage.
    Any structural mismatch between the ORM model and domain model is a clear
    AttributeError here, not a silent data drop.
    """

    return EdiMessageDomainModel(
        id=str(record.id),
        tenant_id=str(record.tenant_id),
        trace_id=str(record.trace_id),
        direction=Direction(record.direction),
        status=RecordStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        format_standard=record.format_standard,
        transaction_type=record.transaction_type,
        connection_type=record.connection_type,
        sender_id=record.sender_id,
        receiver_id=record.receiver_id,
        gs_sender_id=record.gs_sender_id,
        gs_receiver_id=record.gs_receiver_id,
        edi_data=record.edi_data,
        trading_partner_id=record.trading_partner_id,
        storage_uri=record.storage_uri,
    )
