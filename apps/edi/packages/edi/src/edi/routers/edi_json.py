from typing import Any

from fastapi import APIRouter, Depends, status

from edi.adapters.http.dtos import OutboundMessageRequest, OutboundMessageResponse
from edi.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
from edi.dependencies.auth import get_current_tenant_id
from edi.dependencies.database import get_data_plane_uow
from edi.services.api_receiver_service import ApiReceiverService

router = APIRouter(prefix="/api/v1/edi_json", tags=["EDI JSON"])


@router.post(
    "",
    response_model=OutboundMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outbound_message(
    request: OutboundMessageRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: DataPlaneUnitOfWork = Depends(get_data_plane_uow),
) -> Any:
    """
    Submits a JSON payload to be translated and transmitted via AS2.

    Authentication: Single API Token via Bearer Authorization
      Authorization: Bearer <client_id>_<client_secret>
    """
    service = ApiReceiverService(uow=uow)

    trace_id = await service.process_api_edi_json(
        tenant_id=tenant_id,
        trading_partner_id=request.trading_partner_id,
        payload=request.payload,
        transaction_type=request.transaction_type,
    )

    return OutboundMessageResponse(trace_id=trace_id, status="ACCEPTED")
