import logging

from api.domain.models import CreateTradingPartnerRequest, TradingPartnerResponse
from api.ports.repository import ControlPlaneRepositoryPort

logger = logging.getLogger(__name__)


class ProvisioningService:
    """
    Core application service for orchestrating the Provisioning of Trading Partners.
    Decoupled from FastAPI, SQLAlchemy, and AWS.
    """

    def __init__(self, repository: ControlPlaneRepositoryPort) -> None:
        self.repo = repository

    async def provision_trading_partner(
        self, tenant_id: int, request: CreateTradingPartnerRequest
    ) -> TradingPartnerResponse:
        """
        Coordinates the creation of a Trading Partner in the Global Control Plane
        and emits an outbox event for the workers to pick up.
        """
        logger.info(f"Provisioning partner {request.partner_name} for tenant {tenant_id}")

        # 1. Create the Partner
        partner_id = await self.repo.create_trading_partner(
            tenant_id=tenant_id,
            partner_name=request.partner_name,
            as2_id=request.as2_id,
            direction=request.direction,
        )

        # 2. Create the Connection
        await self.repo.create_connection(
            trading_partner_id=partner_id,
            tenant_id=tenant_id,
            request=request,
        )

        # 3. Emit the Outbox Event
        payload = {
            "trading_partner_id": str(partner_id),
            "tenant_id": tenant_id,
        }
        await self.repo.create_outbox_event(
            tenant_id=tenant_id,
            event_type="TRADING_PARTNER_PROVISION",
            payload=payload,
        )

        return TradingPartnerResponse(
            trading_partner_id=partner_id,
            status="PROVISIONING",
            tenant_id=tenant_id,
        )
