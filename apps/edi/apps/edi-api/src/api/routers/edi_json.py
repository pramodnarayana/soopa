from typing import Any

from fastapi import APIRouter, Depends, status

from api.adapters.http.dtos import OutboundMessageRequest, OutboundMessageResponse
from api.auth.api_key import get_tenant_id_from_api_key
from api.core.uow import UnitOfWork
from api.dependencies import get_m2m_tenant_uow
from api.services.api_receiver_service import ApiReceiverService

router = APIRouter(prefix="/api/v1/edi_json", tags=["EDI JSON"])


@router.post(
    "",
    response_model=OutboundMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outbound_message(
    request: OutboundMessageRequest,
    tenant_id: int = Depends(get_tenant_id_from_api_key),
    uow: UnitOfWork = Depends(get_m2m_tenant_uow),
) -> Any:
    """
    Submits a JSON payload to be translated and transmitted via AS2.

    Authentication: Two-part API key (no Zitadel / OAuth2 required).
      X-Client-ID:     soopaedi_<tenant>_<suffix>
      X-Client-Secret: <secret shown once at token creation>
    """
    service = ApiReceiverService(uow=uow)

    trace_id = await service.process_api_edi_json(
        tenant_id=tenant_id,
        trading_partner_id=request.trading_partner_id,
        payload=request.payload,
        transaction_type=request.transaction_type,
    )

    return OutboundMessageResponse(trace_id=trace_id, status="ACCEPTED")
