import structlog

from pipeline.core.delivery.base import BaseDeliveryStrategy
from pipeline.ports.unit_of_work import DataPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeliveryRouter:
    """
    Orchestrates final-mile delivery by delegating to the appropriate strategy.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWork,
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

        for route_key, strategy in self.strategies.items():
            partner_id = route.get(route_key)
            if partner_id:
                try:
                    await strategy.deliver(trace_id, partner_id, edi_msg, idempotency_key)
                except Exception as e:
                    raise RuntimeError(f"Delivery strategy failed for trace_id={trace_id}") from e
                return

        raise ValueError(
            f"Route {route.get('route_id', 'unknown')} is not configured with any destination partner."
        )
