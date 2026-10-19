import asyncio
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import cast

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.encryption import db_encryption
from edi.adapters.outbound.database.tenant_resolver import (
    TenantResolver,
)
from edi.adapters.outbound.database.tenant_uow_provider import (
    TenantUowProvider,
)
from edi.adapters.outbound.pipeline.as2 import HttpxAS2DeliveryClient
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient
from edi.adapters.outbound.pubsub.publisher_factory import create_edi_pipeline_publisher
from edi.adapters.outbound.security.network import validate_target_url
from edi.application.use_cases.pipeline.execute_delivery_use_case import (
    ExecuteDeliveryCommand,
    ExecuteDeliveryUseCase,
)
from edi.application.use_cases.pipeline.fail_delivery_use_case import (
    FailDeliveryCommand,
    FailDeliveryUseCase,
)
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.enums import PipelineEventType, TraceEventType
from observability import ObservabilityProvider
from pubsub.enums import ConsumerAction

DELIVERY_OUTCOME_TO_CONSUMER_ACTION: dict[TraceEventType, ConsumerAction] = {
    TraceEventType.DELIVERY_SUCCESSFUL: ConsumerAction.ACK,
    TraceEventType.DELIVERY_ATTEMPT_FAILED: ConsumerAction.NACK,
    TraceEventType.DELIVERY_FAILED: ConsumerAction.ACK,
}
from edi.domain.exceptions import InvalidMessageError
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.provider import PubSubProvider
from secret_store import SecretStorePort, SecretStoreProvider

from edi_delivery_worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from edi_delivery_worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry
from edi_delivery_worker.settings import WorkerSettings, get_settings

UowFactory = Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]

load_dotenv()
logger = structlog.get_logger(__name__)


def _setup_registry(
    settings: WorkerSettings,
    uow_provider: TenantUowProvider,
    http_delivery: HttpDeliveryPort,
    sftp_delivery: SftpDeliveryPort,
    as2_delivery: AS2DeliveryPort,
    vault: SecretStorePort,
    is_dlq: bool = False,
) -> EdiDataPlaneEventDispatcher:

    publisher = create_edi_pipeline_publisher(
        compute_queue_url=settings.sqs.compute_queue_url,
        orchestrator_queue_url=settings.sqs.orchestrator_queue_url,
        deliver_queue_url=settings.sqs.deliver_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )

    registry = EdiDataPlaneRouteRegistry()

    def use_case_factory(uow_fact: UowFactory) -> ExecuteDeliveryUseCase:
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(uow_fact, http_delivery, vault),
            "sftp_partner_id": SftpDeliveryStrategy(uow_fact, sftp_delivery, vault, db_encryption),
            "as2_partner_id": As2DeliveryStrategy(uow_fact, as2_delivery, vault),
        }
        return ExecuteDeliveryUseCase(
            uow_factory=uow_fact, strategies=strategies, publisher=publisher
        )

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> ConsumerAction:
        try:
            payload_tenant_id = e.payload["tenant_id"]
            if payload_tenant_id != e.tenant_id:
                raise InvalidMessageError(
                    f"Tenant ID mismatch: event tenant_id {e.tenant_id} != payload tenant_id {payload_tenant_id}"
                )

            command = ExecuteDeliveryCommand(
                trace_id=cast(str, e.payload["trace_id"]),
                tenant_id=e.tenant_id,
                partner_id=cast(str, e.payload["partner_id"]),
                strategy_type=cast(str, e.payload["strategy_type"]),
                connection_type=cast(str, e.payload["connection_type"]),
            )
        except KeyError as exc:
            raise InvalidMessageError(
                f"EXECUTE_DELIVERY_COMMAND payload is missing required field: {exc}"
            ) from exc

        outcome = await use_case_factory(uow_fact).execute(
            command=command, idempotency_key=e.idempotency_key
        )
        return DELIVERY_OUTCOME_TO_CONSUMER_ACTION.get(outcome, ConsumerAction.DLQ)

    # DLQ Use Case
    def dlq_use_case_factory(uow_fact: UowFactory) -> FailDeliveryUseCase:
        return FailDeliveryUseCase(uow_factory=uow_fact, publisher=publisher)

    async def run_dlq(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> ConsumerAction:
        try:
            command = FailDeliveryCommand(
                trace_id=cast(str, e.payload["trace_id"]),
                tenant_id=e.tenant_id,
                reason="Max delivery retries exceeded.",
            )
        except KeyError as exc:
            raise InvalidMessageError(
                f"DLQ event payload is missing required field: {exc}"
            ) from exc

        await dlq_use_case_factory(uow_fact).execute(command=command)
        return ConsumerAction.ACK

    # Note: EXECUTE_DELIVERY_COMMAND is the only event this worker listens to
    registry.register(
        event_type=PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
        direction=None,
        factory=run_dlq if is_dlq else run_deliver,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> ConsumerAction:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        return await registry.route(event, uow_factory)

    return EdiDataPlaneEventDispatcher(callback=route_event)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class EdiDeliveryWorkerModule(LaunchableWorker):
    def __init__(self, is_dlq: bool = False) -> None:
        self.is_dlq = is_dlq
        self.db_router: DatabaseRouter | None = None
        self.deliver_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        settings = get_settings()
        aws_endpoint = settings.aws.endpoint_url
        s3_bucket = settings.s3.bucket

        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        assert self.db_router is not None
        resolver = TenantResolver(self.db_router)

        vault = SecretStoreProvider.get_secret_store(secrets_mount_path=settings.secrets.mount_path)

        uow_provider = TenantUowProvider(
            resolver=resolver,
            db_router=self.db_router,
            settings=settings,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        http_delivery = HttpxDeliveryClient(validator=validate_target_url)
        sftp_delivery = ParamikoSftpClient()
        as2_delivery = HttpxAS2DeliveryClient(
            validator=partial(validate_target_url, allow_private_ips=settings.allow_private_ips),
            allow_private_ips=settings.allow_private_ips,
        )

        consumer = _setup_registry(
            settings, uow_provider, http_delivery, sftp_delivery, as2_delivery, vault, self.is_dlq
        )

        if self.is_dlq:
            if not settings.sqs.deliver_dlq_url:
                raise ValueError("SQS_DELIVER_DLQ_URL is required when running in DLQ mode")
            queue_url = settings.sqs.deliver_dlq_url
        else:
            queue_url = settings.sqs.deliver_queue_url

        self.deliver_manager = PubSubProvider.create_consumer_manager(
            queue_url=queue_url,
            handler=consumer.handle,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        assert self.deliver_manager is not None
        self.deliver_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.deliver_manager and self.deliver_manager.task:
            return [self.deliver_manager.task]
        return []

    async def stop(self) -> None:
        logger.info("data_edi_delivery_worker.shutting_down_gracefully")
        if self.deliver_manager:
            results = await asyncio.gather(
                self.deliver_manager.stop(),
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.error("manager_stop_failed", exc_info=res)

        if self.db_router:
            await self.db_router.close_all()


class EdiDeliveryDlqWorkerModule(EdiDeliveryWorkerModule):
    def __init__(self) -> None:
        super().__init__(is_dlq=True)


async def main(stop_event: asyncio.Event | None = None) -> None:
    is_dlq = "--dlq" in sys.argv
    service_name = "edi-delivery-dlq-worker" if is_dlq else "edi-delivery-worker"
    ObservabilityProvider.auto_configure_from_env(service_name)
    module = EdiDeliveryWorkerModule(is_dlq=is_dlq)
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    is_dlq = "--dlq" in sys.argv
    service_name = "edi-delivery-dlq-worker" if is_dlq else "edi-delivery-worker"
    ObservabilityProvider.auto_configure_from_env(service_name)
    run_worker_app(lambda: EdiDeliveryWorkerModule(is_dlq=is_dlq))
