import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from edi.adapters.outbound.database.models.data_plane import ApiGateway, EdiJson, EdiMessage
from edi.adapters.outbound.database.payload_hydration import (
    hydrate_edi_data,
    hydrate_json_payload,
)
from edi.application.dtos.trace import EdiTraceDTO
from edi.application.dtos.transactions import ApiGatewayDTO, EdiJsonDTO, EdiMessageDTO
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.trace_repository import TraceRepositoryPort


class SqlAlchemyTraceRepository(TraceRepositoryPort):
    """
    SQLAlchemy implementation for Trace Projection.
    Strictly responsible for reading the composite Trace view.
    """

    def __init__(self, session: AsyncSession, storage: StoragePort) -> None:
        self.session = session
        self.storage = storage

    async def get_edi_trace(self, tenant_id: str, trace_id: str) -> EdiTraceDTO | None:
        """
        Retrieves a single trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
        """
        tid_str = tenant_id if tenant_id is not None else None
        msg_stmt = (
            select(EdiMessage)
            .where(EdiMessage.tenant_id == tid_str, EdiMessage.trace_id == trace_id)
            .order_by(EdiMessage.created_at.desc())
            .limit(1)
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

        json_records = json_res.scalars().all()

        json_hydration_tasks = [
            hydrate_json_payload(self.storage, j.storage_uri, j.payload) for j in json_records
        ]
        hydrated_json_payloads = await asyncio.gather(*json_hydration_tasks)

        edi_jsons = [
            EdiJsonDTO(
                id=str(j.id),
                trace_id=str(j.trace_id),
                tenant_id=j.tenant_id,
                direction=j.direction,
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
            for j, payload in zip(json_records, hydrated_json_payloads, strict=True)
        ]

        return EdiTraceDTO(
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
                trading_partner_id=edi_msg.trading_partner_id,
                status=edi_msg.status,
                edi_data=await hydrate_edi_data(
                    self.storage, edi_msg.storage_uri, edi_msg.edi_data
                ),
                interchange_control_no=edi_msg.interchange_control_no,
                transaction_type=edi_msg.transaction_type,
                format_standard=edi_msg.format_standard,
                storage_uri=edi_msg.storage_uri,
                file_size_bytes=edi_msg.file_size_bytes,
                msg_headers=None,  # Optimization: Not needed for full trace view currently
                state=edi_msg.state,
                status_message=edi_msg.status_message,
                is_resend=edi_msg.is_resend,
                parent_trace_id=edi_msg.parent_trace_id,
                created_at=edi_msg.created_at,
                updated_at=edi_msg.updated_at,
            ),
            edi_jsons=edi_jsons,
            api_gateways=[
                ApiGatewayDTO(
                    id=str(g.id),
                    trace_id=str(g.trace_id),
                    status=g.status,
                    webhook_url=g.webhook_url,
                    http_status_code=g.http_status_code,
                    payload=g.payload,
                    response=g.response,
                    parent_trace_id=g.parent_trace_id,
                    created_at=g.created_at,
                    updated_at=g.updated_at,
                )
                for g in gw_res.scalars().all()
            ],
        )
