from typing import Any

from fastapi import APIRouter, Depends, status
from identity.dependencies import get_current_tenant_id
from sqlalchemy.ext.asyncio import AsyncSession

from api.adapters.repository import SqlAlchemyControlPlaneRepository
from api.core.provisioning import ProvisioningService
from api.dependencies import get_global_session
from api.domain.models import CreateTradingPartnerRequest, TradingPartnerResponse

router = APIRouter(prefix="/api/v1/trading-partners", tags=["Trading Partners"])


@router.post("", response_model=TradingPartnerResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_trading_partner(
    request: CreateTradingPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_global_session),
) -> Any:
    """
    Creates a new Trading Partner and Connection in the Global Control Plane.
    Emits a provisioning event for workers to replicate this config to the Tenant Data Plane.
    """
    repo = SqlAlchemyControlPlaneRepository(session)
    service = ProvisioningService(repo)

    try:
        response = await service.provision_trading_partner(tenant_id, request)
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise
