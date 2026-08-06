from typing import Any

from fastapi import APIRouter, Depends, status

from api.adapters.http.dtos import OutboundMessageRequest, OutboundMessageResponse
from api.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork as DataPlaneUnitOfWork
from api.auth.api_key import get_tenant_id_from_api_key
from api.dependencies.database import get_m2m_data_plane_uow
from api.services.api_receiver_service import ApiReceiverService

router = APIRouter(prefix="/api/v1/edi_json", tags=["EDI JSON"])


@router.post(
    "",
    response_model=OutboundMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outbound_message(
    request: OutboundMessageRequest,
    tenant_id: str = Depends(get_tenant_id_from_api_key),
    uow: DataPlaneUnitOfWork = Depends(get_m2m_data_plane_uow),
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
