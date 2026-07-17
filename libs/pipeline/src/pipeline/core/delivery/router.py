import logging

from pipeline.core.delivery.base import BaseDeliveryStrategy
from pipeline.ports.repository import RepositoryPort

logger = logging.getLogger(__name__)


class DeliveryRouter:
    """
    Orchestrates final-mile delivery by delegating to the appropriate strategy.
    """

    def __init__(
        self,
        repository: RepositoryPort,
        strategies: dict[str, BaseDeliveryStrategy],
    ) -> None:
        self.repository = repository
        self.strategies = strategies

    async def deliver(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """
        Looks up the route for the given trace_id and dispatches to the
        correct delivery handler via the strategy registry.
        """
        logger.info(f"Starting delivery pipeline for trace_id={trace_id}")

        edi_msg = await self.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI Message found for trace_id={trace_id}")

        direction = edi_msg.direction

        if direction == "OUTBOUND" and edi_msg.trading_partner_id:
            route = await self.repository.get_outbound_route_by_trading_partner_id(
                trading_partner_id=edi_msg.trading_partner_id,
                tenant_id=edi_msg.tenant_id,
            )
            if not route:
                logger.error(
                    f"Configured outbound route for trading_partner_id={edi_msg.trading_partner_id} not found"
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

            route = await self.repository.get_route(
                direction, sender_id, receiver_id, transaction_type
            )
            if not route:
                logger.error(f"No {direction} route found for {sender_id}->{receiver_id}")
                raise ValueError(f"No route found for {direction} {sender_id}->{receiver_id}")

        # ── Dispatch via registry (OCP) ───────────────────────────────────────
        for route_key, strategy in self.strategies.items():
            partner_id = route.get(route_key)
            if partner_id:
                await strategy.deliver(trace_id, partner_id, edi_msg, idempotency_key)
                return

        raise ValueError(
            f"Route {route.get('route_id', 'unknown')} is not configured with any destination partner."
        )
