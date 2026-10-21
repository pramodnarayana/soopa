"""Inbound HTTP router for Integration Platform Ingestion Gateway (L1)."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from identity.domain.identity_context import IdentityContext
from ip.adapters.outbound.database.connection_repository import SqlAlchemyConnectionRepository
from ip.adapters.outbound.database.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.application.ingress.ingest_record_use_case import (
    IngestRecordCommand,
    IngestRecordUseCase,
)
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.dependencies import get_db_session

from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from unified_api.adapters.inbound.http.ip.dtos.ingress_dtos import IngressRecordHttpResponse

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/ingress",
    tags=["Integration Platform - Ingestion Gateway (L1)"],
)


@router.post(
    "/{connection_id}",
    response_model=IngressRecordHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_record(
    tenant_id: str,
    connection_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    stream_name: str = Query(
        ..., alias="stream", description="Target stream name, e.g. meters, contacts"
    ),
    body: Any = Body(...),
    correlation_id: str | None = Header(None, alias="X-Correlation-ID"),
) -> IngressRecordHttpResponse:
    """Captures external raw data payloads with sub-20ms response and enqueues transactional outbox event."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    conn = await connection_repo.get_by_id(connection_id)
    if not conn or conn.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    # Ingest record and drain domain events to outbox in the same transaction
    inbound_repo = SqlAlchemyInboundRecordRepository(session)
    tiered_storage = TieredStorageAdapter()
    use_case = IngestRecordUseCase(inbound_repo=inbound_repo, tiered_storage=tiered_storage)

    cmd = IngestRecordCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
        payload=body,
        headers=dict(request.headers),
        business_correlation_id=correlation_id,
    )

    result = await use_case.execute(cmd)
    await session.commit()

    return IngressRecordHttpResponse(
        record_id=result.record_id,
        business_trace_id=result.business_trace_id,
        status=result.status,
        payload_size_bytes=result.payload_size_bytes,
        is_inlined=result.is_inlined,
    )
