import asyncio
import json
import os
from collections.abc import Sequence
from typing import Protocol, cast

from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id


class RouteModelProtocol(Protocol):
    gs_sender_id: str | None
    gs_receiver_id: str | None
    trading_partner_id: str | None


def _event_idempotency_key(idempotency_key: str | None, *, index: int, event_count: int) -> str:
    base_key = idempotency_key or generate_id(SystemIdPrefix.GENERIC)
    return f"{base_key}_{index}" if event_count > 1 else base_key


from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonValue
from sqlalchemy import CursorResult, Select, and_, or_, select, update
from sqlalchemy.orm import Mapped
from sqlalchemy.sql.elements import ColumnElement

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from edi.adapters.outbound.database.base_repository import TenantSession, TenantSqlAlchemyRepository
from edi.adapters.outbound.database.constants import (
    API_GATEWAY_ID_PREFIX,
    DATA_PLANE_OUTBOX_EVENT_PREFIX,
    EDI_JSON_ID_PREFIX,
)
from edi.adapters.outbound.database.models.data_plane import (
    ApiGateway,
    DataPlaneOutbox,
    EdiJson,
    EdiMessage,
)
from edi.adapters.outbound.database.payload_hydration import (
    hydrate_edi_data,
    hydrate_json_payload,
)
from edi.application.dtos.transactions import (
    EdiJsonDTO,
    EdiMessageDTO,
)
from edi.domain.constants import EDI_MESSAGE_ID_PREFIX
from edi.domain.enums import MessageStatus
from edi.domain.exceptions import IdempotencyConflictError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.transaction_repository import (
    CreateApiGatewayCommand,
    CreateEdiJsonCommand,
    CreateEdiMessageCommand,
    TransactionRepositoryPort,
    UpdateEdiJsonCommand,
)


class SqlAlchemyTransactionRepository(TransactionRepositoryPort, TenantSqlAlchemyRepository):
    def __init__(self, session: TenantSession, storage: StoragePort) -> None:
        TenantSqlAlchemyRepository.__init__(self, session)
        self.storage = storage

    async def claim_edi_message(self, trace_id: str) -> bool:
        stmt = (
            update(EdiMessage)
            .where(
                EdiMessage.trace_id == str(trace_id),
                EdiMessage.status == MessageStatus.PENDING_DELIVERY.value,
            )
            .values(status=MessageStatus.PROCESSING.value)
        )
        result = await self.session.execute(stmt)
        return cast(CursorResult, result).rowcount > 0

    async def create_edi_message(self, command: CreateEdiMessageCommand) -> str:
        msg = EdiMessage(
            id=command.id or f"{EDI_MESSAGE_ID_PREFIX}_{os.urandom(12).hex()}",
            trace_id=command.trace_id,
            tenant_id=command.tenant_id,
            direction=command.direction,
            connection_type=command.connection_type,
            sender_id=command.sender_id,
            receiver_id=command.receiver_id,
            as2_sender_id=command.as2_sender_id,
            as2_receiver_id=command.as2_receiver_id,
            gs_sender_id=command.gs_sender_id,
            gs_receiver_id=command.gs_receiver_id,
            message_id=command.message_id,
            mdn_id=command.mdn_id,
            mdn_mode=command.mdn_mode,
            mdn_response=command.mdn_response,
            file_name=command.file_name,
            content_type=command.content_type,
            signature_algorithm=command.signature_algorithm,
            encryption_algorithm=command.encryption_algorithm,
            trading_partner_id=command.trading_partner_id,
            status=command.status,
            edi_data=command.edi_data,
            interchange_control_no=command.interchange_control_no,
            transaction_type=command.transaction_type,
            format_standard=command.format_standard,
            storage_uri=command.storage_uri,
            file_size_bytes=command.file_size_bytes,
            msg_headers=json.dumps(command.msg_headers) if command.msg_headers else None,
            state=command.state,
            status_message=command.status_message,
            is_resend=command.is_resend,
            parent_trace_id=command.parent_trace_id,
        )
        self.session.add(msg)
        await self.flush()
        return str(msg.id)

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        transaction_type: str | None,
    ) -> None:
        stmt = (
            update(EdiMessage)
            .where(EdiMessage.trace_id == str(trace_id))
            .values(
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                transaction_type=transaction_type,
            )
        )
        await self.session.execute(stmt)

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        stmt = update(EdiMessage).where(EdiMessage.trace_id == str(trace_id)).values(status=status)
        await self.session.execute(stmt)

    async def update_edi_json(self, command: UpdateEdiJsonCommand) -> None:
        values: dict[str, str] = {
            field: getattr(command, field)
            for field in (
                "trading_partner_id",
                "standard",
                "sender_id",
                "receiver_id",
                "gs_sender_id",
                "gs_receiver_id",
            )
            if getattr(command, field) is not None
        }
        if not values:
            return
        stmt = update(EdiJson).where(EdiJson.trace_id == str(command.trace_id)).values(**values)
        await self.session.execute(stmt)

    async def update_edi_json_status(self, trace_id: str, status: str) -> None:
        stmt = update(EdiJson).where(EdiJson.trace_id == str(trace_id)).values(status=status)
        await self.session.execute(stmt)

    async def get_api_payload(self, trace_id: str) -> dict[str, JsonValue] | None:
        stmt = select(ApiGateway).where(ApiGateway.trace_id == str(trace_id)).limit(1)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "payload": record.payload,
            "status": record.status,
            "webhook_url": record.webhook_url,
        }

    async def claim_api_payload(self, trace_id: str) -> bool:
        stmt = (
            update(ApiGateway)
            .where(
                ApiGateway.trace_id == str(trace_id),
                ApiGateway.status == MessageStatus.PENDING_DELIVERY.value,
            )
            .values(status=MessageStatus.PROCESSING.value)
        )
        result = await self.session.execute(stmt)
        return cast(CursorResult, result).rowcount > 0

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        stmt = update(ApiGateway).where(ApiGateway.trace_id == str(trace_id)).values(status=status)
        await self.session.execute(stmt)

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
            idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
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
            idempotency_key = _event_idempotency_key(
                event.idempotency_key,
                index=index,
                event_count=len(aggregate.domain_events),
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
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.flush()
        except DuplicateEntityError as exc:
            # A DB unique constraint on the idempotency key fired — translate to
            # the domain-level error so the application layer can resolve it without
            # any infrastructure leaking through.
            raise IdempotencyConflictError(
                f"EdiJson with idempotency key already exists: {exc}"
            ) from exc

        for index, event in enumerate(aggregate.domain_events):
            event_id = f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}_{os.urandom(12).hex()}"
            idempotency_key = _event_idempotency_key(
                event.idempotency_key,
                index=index,
                event_count=len(aggregate.domain_events),
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

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        stmt = (
            select(EdiJson)
            .where(EdiJson.trace_id == str(trace_id))
            .order_by(EdiJson.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None

        payload = await hydrate_json_payload(self.storage, record.storage_uri, record.payload)

        return EdiJsonDomainModel(
            id=str(record.id),
            trace_id=str(record.trace_id),
            tenant_id=record.tenant_id,
            direction=Direction(record.direction) if record.direction else Direction.OUTBOUND,
            status=MessageStatus(record.status) if record.status else MessageStatus.PENDING,
            trading_partner_id=record.trading_partner_id,
            transaction_type=record.transaction_type,
            standard=record.standard,
            sender_id=record.sender_id,
            receiver_id=record.receiver_id,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            business_metadata=record.business_metadata,
            payload=payload,
            parent_trace_id=record.parent_trace_id,
        )

    async def create_edi_json(self, command: CreateEdiJsonCommand) -> str:
        # Idempotency: if a record already exists for this trace_id + direction + transaction_type
        # return the existing ID without inserting a duplicate.
        if command.trace_id and command.direction and command.transaction_type:
            stmt = (
                select(EdiJson.id)
                .where(
                    EdiJson.trace_id == command.trace_id,
                    EdiJson.direction == command.direction,
                    EdiJson.transaction_type == command.transaction_type,
                )
                .limit(1)
            )
            result = await self.session.execute(stmt)
            existing_id = result.scalar_one_or_none()
            if existing_id:
                return str(existing_id)

        msg = EdiJson(
            id=command.id or f"{EDI_JSON_ID_PREFIX}_{os.urandom(12).hex()}",
            trace_id=command.trace_id,
            tenant_id=command.tenant_id,
            direction=command.direction,
            status=command.status,
            trading_partner_id=command.trading_partner_id,
            standard=command.standard,
            business_metadata=command.business_metadata,
            transaction_type=command.transaction_type,
            sender_id=command.sender_id,
            receiver_id=command.receiver_id,
            gs_sender_id=command.gs_sender_id,
            gs_receiver_id=command.gs_receiver_id,
            payload=command.payload,
            parent_trace_id=command.parent_trace_id,
        )
        self.session.add(msg)
        await self.flush()
        return str(msg.id)

    async def create_api_gateway(self, command: CreateApiGatewayCommand) -> str:
        log = ApiGateway(
            id=command.id or f"{API_GATEWAY_ID_PREFIX}_{os.urandom(12).hex()}",
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            direction=command.direction,
            status=command.status,
            transaction_type=command.transaction_type,
            webhook_url=command.webhook_url,
            http_status_code=command.http_status_code,
            payload=command.payload,
            response=command.response,
            parent_trace_id=command.parent_trace_id,
        )
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
        records = result.scalars().all()

        # 1. Concurrently fetch payloads
        hydration_tasks = [
            hydrate_edi_data(self.storage, r.storage_uri, r.edi_data) for r in records
        ]
        hydrated_payloads = await asyncio.gather(*hydration_tasks)

        # 2. Build frozen DTOs with hydrated payloads
        dtos = [
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
                edi_data=payload,
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
            for r, payload in zip(records, hydrated_payloads, strict=True)
        ]

        return dtos

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
        stmt: Select[tuple[EdiMessage]] | Select[tuple[EdiJson]],
        model: type[EdiMessage] | type[EdiJson],
        filters: list[dict[str, JsonValue]],
    ) -> Select[tuple[EdiMessage]] | Select[tuple[EdiJson]]:

        for f in filters:
            field = f.get("field")
            operator = f.get("operator", "eq")
            value = f.get("value")
            if not isinstance(field, str) or value is None:
                continue

            # Reject unknown fields and operators
            if field not in self._ALLOWED_FIELDS or operator not in self._ALLOWED_OPERATORS:
                continue

            if field == "trading_partner_id":
                if operator == "eq":
                    conds = [
                        model.sender_id == str(value),
                        model.receiver_id == str(value),
                        model.gs_sender_id == str(value),
                        model.gs_receiver_id == str(value),
                        model.trading_partner_id == str(value),
                    ]
                    stmt = stmt.where(or_(*conds))

                elif operator == "neq":
                    conds = [
                        or_(model.sender_id.is_(None), model.sender_id != str(value)),
                        or_(model.receiver_id.is_(None), model.receiver_id != str(value)),
                        or_(model.gs_sender_id.is_(None), model.gs_sender_id != str(value)),
                        or_(model.gs_receiver_id.is_(None), model.gs_receiver_id != str(value)),
                        or_(
                            model.trading_partner_id.is_(None),
                            model.trading_partner_id != str(value),
                        ),
                    ]
                    stmt = stmt.where(and_(*conds))

                elif operator == "contains":
                    escaped_value = (
                        str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    )
                    pattern = f"%{escaped_value}%"
                    conds = [
                        model.sender_id.ilike(pattern, escape="\\"),
                        model.receiver_id.ilike(pattern, escape="\\"),
                        model.gs_sender_id.ilike(pattern, escape="\\"),
                        model.gs_receiver_id.ilike(pattern, escape="\\"),
                        model.trading_partner_id.ilike(pattern, escape="\\"),
                    ]
                    stmt = stmt.where(or_(*conds))

                elif operator == "in" and isinstance(value, list):
                    conds = [
                        model.sender_id.in_(value),
                        model.receiver_id.in_(value),
                        model.gs_sender_id.in_(value),
                        model.gs_receiver_id.in_(value),
                        model.trading_partner_id.in_(value),
                    ]
                    stmt = stmt.where(or_(*conds))
                continue

            if field.startswith("business_metadata.") and issubclass(model, EdiJson):
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
                    json_conds = [column_astext.in_([str(v) for v in value])]
                    for v in value:
                        json_conds.append(model.business_metadata.contains({json_key: v}))
                        json_conds.append(model.business_metadata.contains({json_key: [v]}))
                    stmt = stmt.where(or_(*json_conds))
                continue

            attr: Mapped[object] | None = None
            if field == "direction":
                attr = model.direction
            elif field == "status":
                attr = model.status
            elif field == "transaction_type":
                attr = model.transaction_type
            elif field == "sender_id":
                attr = model.sender_id
            elif field == "receiver_id":
                attr = model.receiver_id
            elif field == "gs_sender_id":
                attr = model.gs_sender_id
            elif field == "gs_receiver_id":
                attr = model.gs_receiver_id
            elif field == "format_standard" and issubclass(model, EdiMessage):
                attr = model.format_standard
            elif field == "connection_type" and issubclass(model, EdiMessage):
                attr = model.connection_type

            if attr is None:
                continue

            if operator == "eq":
                stmt = stmt.where(attr == value)
            elif operator == "neq":
                stmt = stmt.where(attr != value)
            elif operator == "contains":
                escaped_value = (
                    str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                # Mapped[object] typehint in sqlalchemy might not expose ilike, so we cast to string column element
                stmt = stmt.where(
                    cast(ColumnElement[bool], attr.ilike(f"%{escaped_value}%", escape="\\"))
                )
            elif operator == "in" and isinstance(value, list):
                stmt = stmt.where(attr.in_(value))

        return stmt

    async def explorer_list_edi_messages(
        self, tenant_id: str, filters: list[dict[str, JsonValue]], limit: int = 50, offset: int = 0
    ) -> Sequence[EdiMessageDTO]:

        tid_str = tenant_id if tenant_id is not None else None
        base_stmt = select(EdiMessage).where(EdiMessage.tenant_id == tid_str)
        stmt = self._apply_dynamic_filters(
            base_stmt,
            EdiMessage,
            filters,
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
        stmt = self._apply_dynamic_filters(
            base_stmt,
            EdiJson,
            filters,
        )
        stmt = stmt.order_by(EdiJson.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = result.scalars().all()

        hydration_tasks = [
            hydrate_json_payload(self.storage, j.storage_uri, j.payload) for j in records
        ]
        hydrated_payloads = await asyncio.gather(*hydration_tasks)

        dtos = [
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
                payload=payload,
                parent_trace_id=j.parent_trace_id,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j, payload in zip(records, hydrated_payloads, strict=True)
        ]

        return dtos

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJsonDTO]:

        tid_str = tenant_id if tenant_id is not None else None
        json_stmt = (
            select(EdiJson)
            .where(EdiJson.tenant_id == tid_str, EdiJson.business_metadata.contains({key: value}))
            .order_by(EdiJson.created_at.asc())
        )

        result = await self.session.execute(json_stmt)
        records = result.scalars().all()

        hydration_tasks = [
            hydrate_json_payload(self.storage, r.storage_uri, r.payload) for r in records
        ]
        hydrated_payloads = await asyncio.gather(*hydration_tasks)

        dtos = [
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
                payload=payload,
                parent_trace_id=r.parent_trace_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r, payload in zip(records, hydrated_payloads, strict=True)
        ]

        return dtos

    async def get_existing_trace_ids(self, tenant_id: str, trace_ids: list[str]) -> set[str]:

        tid_str = tenant_id if tenant_id is not None else None

        stmt = select(EdiMessage.trace_id).where(
            EdiMessage.tenant_id == tid_str, EdiMessage.trace_id.in_(trace_ids)
        )

        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def get_edi_json_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> EdiJsonDTO | None:
        stmt = (
            select(EdiJson)
            .where(
                EdiJson.tenant_id == tenant_id,
                EdiJson.business_metadata.op("@>")({"_idempotency_key": idempotency_key}),
            )
            .limit(1)
        )

        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if not record:
            return None

        return EdiJsonDTO(
            id=str(record.id),
            trace_id=str(record.trace_id),
            tenant_id=record.tenant_id,
            direction=record.direction,
            status=record.status,
            trading_partner_id=record.trading_partner_id,
            transaction_type=record.transaction_type,
            sender_id=record.sender_id,
            receiver_id=record.receiver_id,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            business_metadata=record.business_metadata,
            payload=record.payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


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
