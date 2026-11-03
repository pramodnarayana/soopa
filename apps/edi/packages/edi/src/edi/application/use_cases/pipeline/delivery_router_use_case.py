import contextlib
from collections.abc import Callable

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_deterministic_id

from edi.domain.exceptions import MissingRoutingInformationError, RouteNotFoundError
from edi.domain.routing.enums import EdiConnectionType, EdiDirection
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.outbound_route import OutboundRoute
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import PipelineEventType
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeliveryRouterUseCase:
    """
    Resolves the delivery route and emits an EXECUTE_DELIVERY_COMMAND to be picked up
    by the dedicated EDI delivery worker.
    """

    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        publisher: OutboxPublisherPort,
    ) -> None:
        self.uow_factory = uow_factory
        self.publisher = publisher

    async def deliver(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """
        Looks up the route for the given trace_id and dispatches to the
        correct delivery handler via the strategy registry.
        """
        logger.info("Starting delivery pipeline for trace_id={trace_id}", trace_id=trace_id)

        async with self.uow_factory() as uow, uow:
            edi_msg = await uow.edi_messages.get_edi_message(trace_id)
            if not edi_msg:
                edi_json = await uow.edi_jsons.get_edi_json(trace_id)
                if edi_json and edi_json.parent_trace_id:
                    edi_msg = await uow.edi_messages.get_edi_message(edi_json.parent_trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI Message found for trace_id={trace_id}")

            if idempotency_key:
                is_new = await uow.record_idempotency(edi_msg.tenant_id, idempotency_key)
                if not is_new:
                    logger.info("delivery_router.duplicate_skipped", trace_id=trace_id)
                    return

            route = await self._resolve_route(edi_msg, uow)

            envelope = await self._dispatch_to_outbox(
                trace_id, route, edi_msg, uow, idempotency_key
            )
            await uow.commit()

        try:
            await self.publisher.publish(envelope)
            async with self.uow_factory() as uow, uow:
                await uow.outbox.mark_completed(envelope.id)
                await uow.commit()
        except Exception as e:
            logger.exception("sync_dispatch_failed_falling_back_to_sweeper", error=str(e))

    async def _resolve_route(
        self, edi_msg: EdiMessage, uow: DataPlaneUnitOfWorkPort
    ) -> OutboundRoute | InboundRoute:
        if edi_msg.direction == EdiDirection.OUTBOUND:
            return await self._get_outbound_route(edi_msg, uow)
        return await self._get_inbound_route(edi_msg, uow)

    async def _get_outbound_route(
        self, edi_msg: EdiMessage, uow: DataPlaneUnitOfWorkPort
    ) -> OutboundRoute:
        if not edi_msg.trading_partner_id:
            raise ValueError(
                f"EDI Message {edi_msg.trace_id} is missing trading_partner_id for OUTBOUND routing."
            )

        route = await uow.outbound_routes.get_outbound_route_by_trading_partner_id(
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
        return route

    async def _get_inbound_route(
        self, edi_msg: EdiMessage, uow: DataPlaneUnitOfWorkPort
    ) -> InboundRoute:
        sender_id = edi_msg.sender_id
        receiver_id = edi_msg.receiver_id
        transaction_type = edi_msg.transaction_type

        if not sender_id or not receiver_id:
            raise MissingRoutingInformationError(trace_id=edi_msg.trace_id)

        logger.debug(
            "looking_up_inbound_route",
            sender_id=sender_id,
            receiver_id=receiver_id,
            tenant_id=edi_msg.tenant_id,
            transaction_type=transaction_type,
        )

        route = await uow.inbound_routes.get_inbound_route(
            isa_sender_id=str(sender_id),
            isa_receiver_id=str(receiver_id),
            tenant_id=str(edi_msg.tenant_id),
            transaction_type=str(transaction_type) if transaction_type else None,
        )
        if not route:
            logger.error(
                "No INBOUND route found for {sender_id}->{receiver_id}",
                sender_id=sender_id,
                receiver_id=receiver_id,
            )
            raise RouteNotFoundError(
                direction="INBOUND", sender_id=str(sender_id), receiver_id=str(receiver_id)
            )
        return route

    @staticmethod
    def _resolve_destination(route: OutboundRoute | InboundRoute) -> tuple[str, str | None]:
        if route.connection_type == EdiConnectionType.SFTP:
            return "sftp_partner_id", route.sftp_partner_id
        if route.connection_type == EdiConnectionType.AS2:
            return "as2_partner_id", route.as2_partner_id
        if route.connection_type == EdiConnectionType.WEBHOOK:
            return "webhook_id", route.webhook_id
        raise ValueError(f"Unsupported connection type: {route.connection_type}")

    async def _dispatch_to_outbox(
        self,
        trace_id: str,
        route: OutboundRoute | InboundRoute,
        edi_msg: EdiMessage,
        uow: DataPlaneUnitOfWorkPort,
        idempotency_key: str | None,
    ) -> EventEnvelope:
        if not route.connection_type:
            route_id = route.id if isinstance(route, OutboundRoute) else "inbound_route"
            raise ValueError(f"Route {route_id} does not specify a connection_type.")

        strategy_type, partner_id = self._resolve_destination(route)

        if not partner_id:
            route_id = route.id if isinstance(route, OutboundRoute) else "inbound_route"
            raise ValueError(
                f"Route {route_id} is configured for {route.connection_type} but destination ID is missing."
            )

        if not idempotency_key:
            raise ValueError("idempotency_key is required for strict event chaining")

        command_key = generate_deterministic_id(
            SystemIdPrefix.IDEMPOTENCY, idempotency_key, "EXECUTE_DELIVERY_COMMAND"
        )

        logger.info(
            "routing.delivery_command_emitted",
            trace_id=trace_id,
            partner_id=partner_id,
            strategy_type=strategy_type,
        )

        envelope = await uow.outbox.append_event(
            tenant_id=edi_msg.tenant_id,
            idempotency_key=command_key,
            event_type=PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
            payload={
                "trace_id": trace_id,
                "tenant_id": edi_msg.tenant_id,
                "partner_id": partner_id,
                "strategy_type": strategy_type,
                "connection_type": route.connection_type,
            },
        )
        return envelope
