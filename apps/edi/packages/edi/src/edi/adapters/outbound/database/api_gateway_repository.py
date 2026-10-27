from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import ApiGateway
from edi.application.dtos.transactions import ApiGatewayDTO
from edi.ports.outbound.api_gateway_repository import (
    ApiGatewayPayloadDTO,
    ApiGatewayRepositoryPort,
    CreateApiGatewayCommand,
)


class SqlAlchemyApiGatewayRepository(ApiGatewayRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_api_gateway(self, command: CreateApiGatewayCommand) -> str:
        log = ApiGateway(
            id=command.id or generate_id(DomainIdPrefix.EDI_API_GATEWAY.value),
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            direction=command.direction,
            status=command.status,
            transaction_type=command.transaction_type,
            webhook_url=command.webhook_url,
            http_status_code=command.http_status_code,
            payload=command.payload,
            response=command.response,
            error_code=command.error_code,
            error_details=command.error_details,
        )
        self.session.add(log)
        await self.session.flush()
        return str(log.id)

    async def get_api_payload(self, trace_id: str) -> ApiGatewayPayloadDTO | None:
        stmt = (
            select(ApiGateway)
            .where(ApiGateway.trace_id == str(trace_id))
            .order_by(ApiGateway.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return ApiGatewayPayloadDTO(
            id=str(record.id),
            trace_id=str(record.trace_id),
            payload=record.payload,
            status=str(record.status),
            http_status_code=record.http_status_code,
            response=record.response,
            error_code=record.error_code,
            error_details=record.error_details,
        )

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayDTO]:
        tid_str = tenant_id if tenant_id is not None else None
        stmt = (
            select(ApiGateway)
            .where(ApiGateway.tenant_id == tid_str, ApiGateway.trace_id == str(trace_id))
            .order_by(ApiGateway.created_at.asc())
        )
        result = await self.session.execute(stmt)
        gw_records = result.scalars().all()
        return [
            ApiGatewayDTO(
                id=str(g.id),
                trace_id=str(g.trace_id),
                status=g.status,
                webhook_url=g.webhook_url,
                http_status_code=g.http_status_code,
                payload=g.payload,
                response=g.response,
                error_code=g.error_code,
                error_details=g.error_details,
                created_at=g.created_at,
                updated_at=g.updated_at,
                replay_count=g.replay_count,
                original_trace_id=g.original_trace_id,
                parent_trace_id=g.parent_trace_id,
            )
            for g in gw_records
        ]

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        record_id: str | None = None,
    ) -> None:
        if record_id:
            stmt = update(ApiGateway).where(ApiGateway.id == record_id).values(status=status)
        else:
            # Fallback to updating the latest record for this trace_id if no record_id is provided
            subq = (
                select(ApiGateway.id)
                .where(ApiGateway.trace_id == str(trace_id))
                .order_by(ApiGateway.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            stmt = update(ApiGateway).where(ApiGateway.id == subq).values(status=status)

        if webhook_url is not None:
            stmt = stmt.values(webhook_url=webhook_url)
        if http_status_code is not None:
            stmt = stmt.values(http_status_code=http_status_code)
        if response is not None:
            stmt = stmt.values(response=response)
        if error_code is not None:
            stmt = stmt.values(error_code=error_code)
        if error_details is not None:
            stmt = stmt.values(error_details=error_details)

        await self.session.execute(stmt)
        await self.session.flush()
