import asyncio
from collections.abc import Callable
from typing import Any

import structlog
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import (
    TenantResolver,
)
from edi.adapters.outbound.database.tenant_uow_provider import (
    TenantUowProvider,
)
from edi.adapters.outbound.pipeline.as2 import HttpxAS2DeliveryClient
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.adapters.outbound.security.network import validate_target_url
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.pipeline_lifecycle_use_case import PipelineLifecycleUseCase
from edi.config.settings import get_settings
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.events import MessageQueueName, PipelineEventType
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from worker.adapters.aws_secrets_manager import AwsSecretsManagerSecretStore
from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry

load_dotenv()
logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    # ─────────────────────────────────────────────────────────────
    # Inbound SQS Adapters (Hexagonal: Protocol Translation Only)
    # ─────────────────────────────────────────────────────────────
    transformer = BotsTransformerAdapter()
    vault = AwsSecretsManagerSecretStore()

    uow_provider = TenantUowProvider(
        resolver=resolver,
        db_router=db_router,
        settings=settings,
        s3_bucket=s3_bucket,
        aws_endpoint=aws_endpoint,
    )

    http_delivery = HttpxDeliveryClient(validator=validate_target_url)
    sftp_delivery = ParamikoSftpClient()
    as2_delivery = HttpxAS2DeliveryClient(validator=validate_target_url)

    def router_factory(uow: DataPlaneUnitOfWorkPort) -> DeliveryRouterUseCase:
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(uow, http_delivery, vault),
            "sftp_partner_id": SftpDeliveryStrategy(uow, sftp_delivery, vault),
            "as2_partner_id": As2DeliveryStrategy(uow, as2_delivery, vault),
        }
        return DeliveryRouterUseCase(uow=uow, strategies=strategies)

    registry = EdiDataPlaneRouteRegistry()

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            await DispatchInboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_outbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            await DispatchOutboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_transform_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_transform_completed(e.payload)

    async def run_delivery_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_delivery_completed(e.payload)

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        await DeliveryUseCase(uow_factory=uow_fact, router_factory=router_factory).execute(
            trace_id=e.trace_id, idempotency_key=e.idempotency_key
        )

    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="INBOUND",
        factory=run_inbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="OUTBOUND",
        factory=run_outbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
        direction=None,
        factory=run_transform_lifecycle,
    )
    registry.register(
        event_type=PipelineEventType.DELIVER_EVENT.value,
        direction=None,
        factory=run_deliver,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_COMPLETED.value,
        direction=None,
        factory=run_delivery_lifecycle,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        await registry.route(event, uow_factory)

    consumer = EdiDataPlaneEventDispatcher(callback=route_event)

    transform_manager = SqsConsumerManager(
        queue_name=MessageQueueName.TRANSFORM_QUEUE,
        handler=consumer.handle,
        endpoint_url=aws_endpoint,
    )
    transform_manager.start()

    lifecycle_manager = SqsConsumerManager(
        queue_name=MessageQueueName.LIFECYCLE_QUEUE,
        handler=consumer.handle,
        endpoint_url=aws_endpoint,
    )
    lifecycle_manager.start()

    deliver_manager = SqsConsumerManager(
        queue_name=MessageQueueName.DELIVER_QUEUE,
        handler=consumer.handle,
        endpoint_url=aws_endpoint,
    )
    deliver_manager.start()

    # ─────────────────────────────────────────────────────────────
    # Run all workers concurrently
    # ─────────────────────────────────────────────────────────────
    stop_event = asyncio.Event()
    try:
        import signal

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    finally:
        logger.info("data_worker.shutting_down_gracefully")
        await transform_manager.stop()
        await lifecycle_manager.stop()
        await deliver_manager.stop()

        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
