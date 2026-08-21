import uuid
from collections.abc import Sequence
from typing import Any

from database.base_repository import TenantSession, TenantSqlAlchemyRepository
from database.constants import EDI_JSON_ID_PREFIX, EDI_MESSAGE_ID_PREFIX
from database.models.data_plane import EdiMessage
from sqlalchemy import or_, select

from edi.domain.models import (
    ApiGatewayDTO,
    EdiJsonDTO,
    EdiMessageDTO,
    TransactionDetailDTO,
)
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort


class SqlAlchemyTransactionRepository(TransactionRepositoryPort, TenantSqlAlchemyRepository):
    def __init__(self, session: TenantSession) -> None:
        TenantSqlAlchemyRepository.__init__(self, session)

    async def create_edi_message(self, tenant_id: str, payload: dict[str, Any]) -> str:
        tid_str = tenant_id if tenant_id is not None else None
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{EDI_MESSAGE_ID_PREFIX}{uuid.uuid4().hex}"
        msg = EdiMessage(tenant_id=tid_str, **payload_copy)
        self.session.add(msg)
        await self.session.flush()
        return str(msg.id)

    async def publish_outbox_event(
        self, tenant_id: str, event_type: str, payload: dict[str, Any], idempotency_key: str | None
    ) -> str:
        from database.constants import DATA_PLANE_OUTBOX_EVENT_PREFIX
        from database.models.data_plane import DataPlaneOutbox

        tid_str = tenant_id if tenant_id is not None else None
        event_id = f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}{uuid.uuid4().hex}"
        record = DataPlaneOutbox(
            id=event_id,
            tenant_id=tid_str,
            idempotency_key=idempotency_key,
            event_type=event_type,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return str(event_id)

    async def create_edi_json(self, tenant_id: str, payload: dict[str, Any]) -> str:
        from database.models.data_plane import EdiJson

        tid_str = tenant_id if tenant_id is not None else None
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{EDI_JSON_ID_PREFIX}{uuid.uuid4().hex}"
        msg = EdiJson(tenant_id=tid_str, **payload_copy)
        self.session.add(msg)
        await self.session.flush()
        return str(msg.id)

    async def create_api_gateway(self, tenant_id: str, payload: dict[str, Any]) -> str:
        from database.constants import API_GATEWAY_ID_PREFIX
        from database.models.data_plane import ApiGateway

        tid_str = tenant_id if tenant_id is not None else None
        payload_copy = dict(payload)
        if "id" not in payload_copy:
            payload_copy["id"] = f"{API_GATEWAY_ID_PREFIX}{uuid.uuid4().hex}"
        log = ApiGateway(tenant_id=tid_str, **payload_copy)
        self.session.add(log)
        await self.session.flush()
        return str(log.id)

    async def list_transactions(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[Any]:
        from database.models.data_plane import EdiMessage

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
        return result.scalars().all()

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

    def _apply_dynamic_filters(self, stmt: Any, model: Any, filters: list[dict[str, Any]]) -> Any:
        from sqlalchemy import and_, or_

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
                                [model.gs_sender_id == value, model.gs_receiver_id == value]
                            )
                        if has_tp:
                            conds.append(model.trading_partner_id == value)
                        stmt = stmt.where(or_(*conds))

                    elif operator == "neq":
                        conds = [model.sender_id != value, model.receiver_id != value]
                        if has_gs:
                            conds.extend(
                                [model.gs_sender_id != value, model.gs_receiver_id != value]
                            )
                        if has_tp:
                            conds.append(model.trading_partner_id != value)
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
                                    model.gs_sender_id.ilike(pattern, escape="\\"),
                                    model.gs_receiver_id.ilike(pattern, escape="\\"),
                                ]
                            )
                        if has_tp:
                            conds.append(model.trading_partner_id.ilike(pattern, escape="\\"))
                        stmt = stmt.where(or_(*conds))

                    elif operator == "in" and isinstance(value, list):
                        conds = [model.sender_id.in_(value), model.receiver_id.in_(value)]
                        if has_gs:
                            conds.extend(
                                [model.gs_sender_id.in_(value), model.gs_receiver_id.in_(value)]
                            )
                        if has_tp:
                            conds.append(model.trading_partner_id.in_(value))
                        stmt = stmt.where(or_(*conds))
                continue

            if field.startswith("business_metadata.") and hasattr(model, "business_metadata"):
                json_key = field.split("business_metadata.")[1]
                column = model.business_metadata[json_key]
                column_astext = column.astext
                if operator == "eq":
                    from sqlalchemy import or_

                    stmt = stmt.where(
                        or_(
                            column_astext == str(value),
                            model.business_metadata.contains({json_key: value}),
                            model.business_metadata.contains({json_key: [value]}),
                        )
                    )
                elif operator == "neq":
                    from sqlalchemy import and_

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
                    from sqlalchemy import or_

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
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> Sequence[Any]:
        from database.models.data_plane import EdiMessage

        tid_str = tenant_id if tenant_id is not None else None
        stmt = select(EdiMessage).where(EdiMessage.tenant_id == tid_str)
        stmt = self._apply_dynamic_filters(stmt, EdiMessage, filters)
        stmt = stmt.order_by(EdiMessage.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def explorer_list_edi_json(
        self, tenant_id: str, filters: list[dict[str, Any]], limit: int = 50, offset: int = 0
    ) -> Sequence[Any]:
        from database.models.data_plane import EdiJson

        tid_str = tenant_id if tenant_id is not None else None
        stmt = select(EdiJson).where(EdiJson.tenant_id == tid_str)
        stmt = self._apply_dynamic_filters(stmt, EdiJson, filters)
        stmt = stmt.order_by(EdiJson.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_transaction(self, tenant_id: str, trace_id: str) -> TransactionDetailDTO | None:

        from database.models.data_plane import ApiGateway, EdiJson, EdiMessage

        tid_str = tenant_id if tenant_id is not None else None
        msg_stmt = select(EdiMessage).where(
            EdiMessage.tenant_id == tid_str, EdiMessage.trace_id == trace_id
        )
        json_stmt = (
            select(EdiJson)
            .where(EdiJson.tenant_id == tid_str, EdiJson.trace_id == trace_id)
            .order_by(EdiJson.created_at.asc())
        )
        gw_stmt = (
            select(ApiGateway)
            .where(ApiGateway.tenant_id == tid_str, ApiGateway.trace_id == trace_id)
            .order_by(ApiGateway.created_at.asc())
        )

        msg_res = await self.session.execute(msg_stmt)
        edi_msg = msg_res.scalars().first()

        if not edi_msg:
            return None

        json_res = await self.session.execute(json_stmt)
        gw_res = await self.session.execute(gw_stmt)

        return TransactionDetailDTO(
            edi_message=EdiMessageDTO(
                id=str(edi_msg.id),
                trace_id=str(edi_msg.trace_id),
                direction=edi_msg.direction,
                connection_type=edi_msg.connection_type,
                sender_id=edi_msg.sender_id,
                receiver_id=edi_msg.receiver_id,
                as2_sender_id=edi_msg.as2_sender_id,
                as2_receiver_id=edi_msg.as2_receiver_id,
                gs_sender_id=edi_msg.gs_sender_id,
                gs_receiver_id=edi_msg.gs_receiver_id,
                message_id=edi_msg.message_id,
                mdn_id=edi_msg.mdn_id,
                mdn_mode=edi_msg.mdn_mode,
                mdn_response=edi_msg.mdn_response,
                file_name=edi_msg.file_name,
                content_type=edi_msg.content_type,
                signature_algorithm=edi_msg.signature_algorithm,
                encryption_algorithm=edi_msg.encryption_algorithm,
                compression=getattr(edi_msg, "compression", None),
                inbound_route_id=getattr(edi_msg, "inbound_route_id", None),
                trading_partner_id=getattr(edi_msg, "trading_partner_id", None),
                status=getattr(edi_msg, "status", "RECEIVED"),
                edi_data=getattr(edi_msg, "edi_data", None),
                interchange_control_no=getattr(edi_msg, "interchange_control_no", None),
                transaction_type=getattr(edi_msg, "transaction_type", None),
                format_standard=getattr(edi_msg, "format_standard", None),
                storage_uri=getattr(edi_msg, "storage_uri", None),
                file_size_bytes=getattr(edi_msg, "file_size_bytes", None),
                msg_headers=getattr(edi_msg, "msg_headers", None),
                state=getattr(edi_msg, "state", None),
                status_message=getattr(edi_msg, "status_message", None),
                is_resend=getattr(edi_msg, "is_resend", False),
                parent_trace_id=getattr(edi_msg, "parent_trace_id", None),
                created_at=edi_msg.created_at,
                updated_at=edi_msg.updated_at,
            ),
            edi_jsons=[
                EdiJsonDTO(
                    id=str(j.id),
                    trace_id=str(j.trace_id),
                    status=j.status,
                    trading_partner_id=getattr(j, "trading_partner_id", None),
                    error_message=getattr(j, "error_message", None),
                    interchange_control_number=getattr(j, "interchange_control_number", None),
                    group_control_number=getattr(j, "group_control_number", None),
                    transaction_set_control_number=getattr(
                        j, "transaction_set_control_number", None
                    ),
                    business_metadata=j.business_metadata,
                    processing_metadata=getattr(j, "processing_metadata", None),
                    transaction_type=getattr(j, "transaction_type", None),
                    sender_id=getattr(j, "sender_id", None),
                    receiver_id=getattr(j, "receiver_id", None),
                    gs_sender_id=getattr(j, "gs_sender_id", None),
                    gs_receiver_id=getattr(j, "gs_receiver_id", None),
                    payload=getattr(j, "payload", None),
                    parent_trace_id=getattr(j, "parent_trace_id", None),
                    created_at=j.created_at,
                    updated_at=j.updated_at,
                )
                for j in json_res.scalars().all()
            ],
            api_gateways=[
                ApiGatewayDTO(
                    id=str(g.id),
                    trace_id=str(g.trace_id),
                    event_type=getattr(g, "event_type", None),
                    status=getattr(g, "status", None),
                    error_message=getattr(g, "error_message", None),
                    webhook_url=getattr(g, "webhook_url", None),
                    http_status_code=getattr(g, "http_status_code", None),
                    payload=getattr(g, "payload", None),
                    response=getattr(g, "response", None),
                    parent_trace_id=getattr(g, "parent_trace_id", None),
                    created_at=g.created_at,
                    updated_at=g.updated_at,
                )
                for g in gw_res.scalars().all()
            ],
        )

    async def get_transaction_thread(self, tenant_id: str, key: str, value: str) -> Sequence[Any]:
        from database.models.data_plane import EdiJson

        tid_str = tenant_id if tenant_id is not None else None
        json_stmt = (
            select(EdiJson)
            .where(EdiJson.tenant_id == tid_str, EdiJson.business_metadata.contains({key: value}))
            .order_by(EdiJson.created_at.asc())
        )

        result = await self.session.execute(json_stmt)
        return result.scalars().all()

    async def get_existing_trace_ids(self, tenant_id: str, trace_ids: list[str]) -> set[str]:
        from database.models.data_plane import EdiMessage
        from sqlalchemy import select

        tid_str = tenant_id if tenant_id is not None else None

        stmt = select(EdiMessage.trace_id).where(
            EdiMessage.tenant_id == tid_str, EdiMessage.trace_id.in_(trace_ids)
        )

        result = await self.session.execute(stmt)
        return set(result.scalars().all())
