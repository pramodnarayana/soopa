from typing import Any, cast

from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWorkPort,
)
from edi.application.dtos import ProcessApiEdiJsonCommand
from edi.application.use_cases.process_api_edi_json_use_case import ProcessApiEdiJsonUseCase
from fastapi import APIRouter, Depends, status
from seedwork.domain.types import JsonValue

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_data_plane_uow
from unified_api.adapters.inbound.http.dtos.edi.dtos import (
    OutboundMessageRequest,
    OutboundMessageResponse,
    OutboundMessageStatus,
)

router = APIRouter(prefix="/api/v1/edi_json", tags=["EDI JSON"])


@router.post(
    "",
    response_model=OutboundMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outbound_message(
    request: OutboundMessageRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWorkPort = Depends(get_data_plane_uow),
) -> Any:
    """
    Submits a JSON payload to be translated and transmitted via AS2.

    Authentication: Single API Token via Bearer Authorization
      Authorization: Bearer <client_id>_<client_secret>
    """
    service = ProcessApiEdiJsonUseCase(uow=uow)

    trace_id = await service.process_api_edi_json(
        ProcessApiEdiJsonCommand(
            tenant_id=tenant_id,
            trading_partner_id=request.trading_partner_id,
            payload=cast(JsonValue, request.payload),
            transaction_type=request.transaction_type,
        )
    )

    return OutboundMessageResponse(trace_id=trace_id, status=OutboundMessageStatus.ACCEPTED)
