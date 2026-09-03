from typing import Any

import structlog

from edi.application.dtos.routes import OutboundRouteDTO
from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeliveryRouterUseCase:
    """
    Orchestrates final-mile delivery by delegating to the appropriate strategy.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        strategies: dict[str, BaseDeliveryStrategy],
    ) -> None:
        self.uow = uow
        self.strategies = strategies

    async def deliver(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """
        Looks up the route for the given trace_id and dispatches to the
        correct delivery handler via the strategy registry.
        """
        logger.info("Starting delivery pipeline for trace_id={trace_id}", trace_id=trace_id)

        edi_msg = await self.uow.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI Message found for trace_id={trace_id}")

        direction = edi_msg.direction

        route: Any = None
        if direction == "OUTBOUND":
            if not edi_msg.trading_partner_id:
                raise ValueError(
                    f"EDI Message {trace_id} is missing trading_partner_id for OUTBOUND routing."
                )

            route = await self.uow.repository.get_outbound_route_by_trading_partner_id(
                trading_partner_id=edi_msg.trading_partner_id,
                tenant_id=edi_msg.tenant_id,
            )
            if not route:
                logger.error(
                    "Configured outbound route for trading_partner_id={trading_partner_id} not found",
                    trading_partner_id=edi_msg.trading_partner_id,
                )
                raise ValueError(
                    f"Configured outbound route for trading_partner_id={edi_msg.trading_partner_id} not found"
                )
        else:
            sender_id = edi_msg.sender_id
            receiver_id = edi_msg.receiver_id
            transaction_type = edi_msg.transaction_type or "*"

            if not sender_id or not receiver_id:
                raise ValueError(
                    f"EDI Message {trace_id} is missing sender/receiver IDs for routing."
                )

            route = await self.uow.repository.get_route(
                direction, sender_id, receiver_id, transaction_type
            )
            if not route:
                logger.error(
                    "No {direction} route found for {sender_id}->{receiver_id}",
                    direction=direction,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                )
                raise ValueError(f"No route found for {direction} {sender_id}->{receiver_id}")

        partner_id = None
        strategy = None

        if route.sftp_partner_id:
            partner_id = route.sftp_partner_id
            strategy = self.strategies["sftp_partner_id"]
        elif route.as2_partner_id:
            partner_id = route.as2_partner_id
            strategy = self.strategies["as2_partner_id"]
        elif route.webhook_id:
            partner_id = route.webhook_id
            strategy = self.strategies["webhook_id"]

        if partner_id and strategy:
            try:
                await strategy.deliver(trace_id, partner_id, edi_msg, idempotency_key)
            except Exception as e:
                raise RuntimeError(f"Delivery strategy failed for trace_id={trace_id}") from e
            return

        route_id = route.route_id if isinstance(route, OutboundRouteDTO) else "inbound_route"
        raise ValueError(
            f"Route {route_id} is not configured with any destination partner."
        )
