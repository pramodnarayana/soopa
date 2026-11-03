from __future__ import annotations

from typing import cast

from seedwork.domain.types import JsonDict, JsonValue
from seedwork.utils import generate_id
from sqlalchemy import select, update

from database.types import TenantSession
from edi.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from edi.adapters.outbound.database.models.data_plane import ApiGateway
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt
from edi.ports.outbound.api_gateway_repository import ApiGatewayRepositoryPort


class SqlAlchemyApiGatewayRepository(TenantSqlAlchemyRepository, ApiGatewayRepositoryPort):
    def __init__(self, session: TenantSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: ApiGateway) -> ApiGatewayReceipt:
        """Explicit ORM -> Domain mapper for ApiGatewayReceipt."""
        return ApiGatewayReceipt(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            trace_id=str(record.trace_id),
            direction=(
                EdiDirection(record.direction) if record.direction else EdiDirection.INBOUND
            ),
            status=MessageStatus(record.status) if record.status else MessageStatus.PENDING,
            created_at=record.created_at,
            updated_at=record.updated_at,
            error_code=record.error_code,
            error_details=record.error_details,
            transaction_type=record.transaction_type,
            webhook_url=record.webhook_url,
            http_status_code=record.http_status_code,
            target_format=record.target_format,
            payload=record.payload,
            storage_uri=record.storage_uri,
            response=record.response,
            headers=record.headers,
            replay_count=record.replay_count,
            parent_trace_id=record.parent_trace_id,
            original_trace_id=record.original_trace_id,
        )

    @staticmethod
    def _to_orm_record(receipt: ApiGatewayReceipt) -> ApiGateway:
        """Explicit Domain -> ORM mapper for ApiGatewayReceipt."""
        record_id = receipt.id if receipt.id else generate_id(DomainIdPrefix.EDI_API_GATEWAY.value)
        return ApiGateway(
            id=record_id,
            tenant_id=receipt.tenant_id,
            trace_id=receipt.trace_id,
            direction=receipt.direction.value if receipt.direction else None,
            status=receipt.status.value if receipt.status else None,
            transaction_type=receipt.transaction_type,
            webhook_url=receipt.webhook_url,
            http_status_code=receipt.http_status_code,
            target_format=receipt.target_format,
            payload=cast(dict[str, JsonValue] | None, receipt.payload),
            storage_uri=receipt.storage_uri,
            response=receipt.response,
            headers=receipt.headers,
            error_code=receipt.error_code,
            error_details=receipt.error_details,
            replay_count=receipt.replay_count,
            parent_trace_id=receipt.parent_trace_id,
            original_trace_id=receipt.original_trace_id,
        )

    @staticmethod
    def _update_record_from_domain(record: ApiGateway, receipt: ApiGatewayReceipt) -> None:
        """Explicit Domain -> ORM mutation mapper for ApiGatewayReceipt."""
        if receipt.direction:
            record.direction = receipt.direction.value
        if receipt.status:
            record.status = receipt.status.value
        record.transaction_type = receipt.transaction_type
        record.webhook_url = receipt.webhook_url
        record.http_status_code = receipt.http_status_code
        record.target_format = receipt.target_format
        record.payload = cast(dict[str, JsonValue] | None, receipt.payload)
        record.storage_uri = receipt.storage_uri
        record.response = receipt.response
        record.headers = receipt.headers
        record.error_code = receipt.error_code
        record.error_details = receipt.error_details
        record.replay_count = receipt.replay_count
        record.parent_trace_id = receipt.parent_trace_id
        record.original_trace_id = receipt.original_trace_id

    async def save(self, receipt: ApiGatewayReceipt) -> str:
        orm_record = self._to_orm_record(receipt)
        await self.session.merge(orm_record)
        await self.flush()
        return str(orm_record.id)

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayReceipt]:
        tid_str = tenant_id if tenant_id is not None else None
        stmt = (
            select(ApiGateway)
            .where(ApiGateway.tenant_id == tid_str, ApiGateway.trace_id == str(trace_id))
            .order_by(ApiGateway.created_at.asc())
        )
        result = await self.session.execute(stmt)
        gw_records = result.scalars().all()
        return [self._to_domain_model(record) for record in gw_records]

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: MessageStatus,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        record_id: str | None = None,
    ) -> None:
        if record_id:
            stmt = update(ApiGateway).where(ApiGateway.id == record_id).values(status=status.value)
        else:
            subq = (
                select(ApiGateway.id)
                .where(ApiGateway.trace_id == str(trace_id))
                .order_by(ApiGateway.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            stmt = update(ApiGateway).where(ApiGateway.id == subq).values(status=status.value)

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
        await self.flush()
