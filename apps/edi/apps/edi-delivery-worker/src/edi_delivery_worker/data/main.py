import asyncio
import sys
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import Protocol

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.adapters.outbound.pipeline.as2 import HttpxAS2DeliveryClient
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient
from edi.adapters.outbound.security.network import validate_target_url
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.application.use_cases.pipeline.execute_delivery_use_case import (
    ExecuteDeliveryCommand,
    ExecuteDeliveryUseCase,
)
from edi.application.use_cases.pipeline.fail_delivery_use_case import (
    FailDeliveryCommand,
    FailDeliveryUseCase,
)
from edi.bootstrap.container import create_edi_tenant_uow_provider
from edi.bootstrap.publisher_factory import create_edi_pipeline_publisher
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.enums import EdiTraceEventType
from edi.domain.exceptions import InvalidMessageError
from edi.domain.transaction.enums import PipelineEventType
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.crypto_service_port import CryptoServicePort
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from observability import ObservabilityProvider
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.enums import ConsumerAction
from pubsub.exceptions import ConsumerTerminalError
from pubsub.provider import PubSubProvider
from secret_store import SecretStorePort, SecretStoreProvider
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async
from sharding.domain.exceptions import TenantNotFoundError

from edi_delivery_worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from edi_delivery_worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry
from edi_delivery_worker.settings import WorkerSettings, get_settings

UowFactory = Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]


class TenantUoWProviderPort(Protocol):
    async def get_uow_factory(self, tenant_id: str) -> UowFactory: ...


DELIVERY_OUTCOME_TO_CONSUMER_ACTION: dict[EdiTraceEventType, ConsumerAction] = {
    EdiTraceEventType.DELIVERY_SUCCESSFUL: ConsumerAction.ACK,
    EdiTraceEventType.DELIVERY_ATTEMPT_FAILED: ConsumerAction.NACK,
    EdiTraceEventType.DELIVERY_FAILED: ConsumerAction.ACK,
}

load_dotenv()
logger = structlog.get_logger(__name__)


def _require_str_field(payload: Mapping[str, object], field_name: str, context: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise InvalidMessageError(
            f"{context} payload is missing required string field: '{field_name}'"
        )
    return value


def _build_delivery_route_registry(
    publisher: OutboxPublisherPort,
    http_delivery: HttpDeliveryPort,
    sftp_delivery: SftpDeliveryPort,
    as2_delivery: AS2DeliveryPort,
    vault: SecretStorePort,
    field_encryption: CipherPort | None = None,
    crypto_service: CryptoServicePort | None = None,
) -> EdiDataPlaneRouteRegistry:
    registry = EdiDataPlaneRouteRegistry()
    resolved_crypto = crypto_service or SmimeCryptoService()

    def use_case_factory(uow_fact: UowFactory) -> ExecuteDeliveryUseCase:
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(uow_fact, http_delivery, vault),
            "sftp_partner_id": SftpDeliveryStrategy(
                uow_fact, sftp_delivery, vault, field_encryption
            ),
            "as2_partner_id": As2DeliveryStrategy(
                uow_fact, as2_delivery, vault, crypto_service=resolved_crypto
            ),
        }
        return ExecuteDeliveryUseCase(
            uow_factory=uow_fact, strategies=strategies, publisher=publisher
        )

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> ConsumerAction:
        payload_tenant_id = _require_str_field(e.payload, "tenant_id", "EXECUTE_DELIVERY_COMMAND")
        if payload_tenant_id != e.tenant_id:
            raise InvalidMessageError(
                f"Tenant ID mismatch: event tenant_id {e.tenant_id} != payload tenant_id {payload_tenant_id}"
            )

        command = ExecuteDeliveryCommand(
            trace_id=_require_str_field(e.payload, "trace_id", "EXECUTE_DELIVERY_COMMAND"),
            tenant_id=e.tenant_id,
            partner_id=_require_str_field(e.payload, "partner_id", "EXECUTE_DELIVERY_COMMAND"),
            strategy_type=_require_str_field(
                e.payload, "strategy_type", "EXECUTE_DELIVERY_COMMAND"
            ),
            connection_type=_require_str_field(
                e.payload, "connection_type", "EXECUTE_DELIVERY_COMMAND"
            ),
        )

        outcome = await use_case_factory(uow_fact).execute(
            command=command, idempotency_key=e.idempotency_key
        )
        return DELIVERY_OUTCOME_TO_CONSUMER_ACTION.get(outcome, ConsumerAction.DLQ)

    registry.register(
        event_type=PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
        direction=None,
        factory=run_deliver,
    )
    return registry


def _build_dlq_route_registry(
    publisher: OutboxPublisherPort,
) -> EdiDataPlaneRouteRegistry:
    registry = EdiDataPlaneRouteRegistry()

    async def run_dlq(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> ConsumerAction:
        command = FailDeliveryCommand(
            trace_id=_require_str_field(e.payload, "trace_id", "DLQ"),
            tenant_id=e.tenant_id,
            reason="Max delivery retries exceeded.",
        )
        await FailDeliveryUseCase(uow_factory=uow_fact, publisher=publisher).execute(
            command=command
        )
        return ConsumerAction.ACK

    registry.register(
        event_type=PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
        direction=None,
        factory=run_dlq,
    )
    return registry


def _build_dispatcher_from_registry(
    registry: EdiDataPlaneRouteRegistry,
    uow_provider: TenantUoWProviderPort,
) -> EdiDataPlaneEventDispatcher:
    async def route_event(event: EdiDataPlaneEventMessage) -> ConsumerAction:
        try:
            uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        except TenantNotFoundError as exc:
            logger.error(
                "edi_delivery_worker.tenant_not_found_terminal_error",
                tenant_id=event.tenant_id,
                trace_id=event.trace_id,
                error=str(exc),
            )
            raise ConsumerTerminalError(f"Tenant {event.tenant_id} not found in Global DB") from exc
        return await registry.route(event, uow_factory)

    return EdiDataPlaneEventDispatcher(callback=route_event)


def _create_default_publisher(settings: WorkerSettings) -> OutboxPublisherPort:
    return create_edi_pipeline_publisher(
        compute_queue_url=settings.sqs.compute_queue_url,
        orchestrator_queue_url=settings.sqs.orchestrator_queue_url,
        deliver_queue_url=settings.sqs.deliver_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )


def _setup_registry(
    settings: WorkerSettings,
    uow_provider: TenantUoWProviderPort,
    http_delivery: HttpDeliveryPort,
    sftp_delivery: SftpDeliveryPort,
    as2_delivery: AS2DeliveryPort,
    vault: SecretStorePort,
    publisher: OutboxPublisherPort | None = None,
    field_encryption: CipherPort | None = None,
    crypto_service: CryptoServicePort | None = None,
) -> EdiDataPlaneEventDispatcher:
    resolved_publisher = publisher or _create_default_publisher(settings)
    registry = _build_delivery_route_registry(
        publisher=resolved_publisher,
        http_delivery=http_delivery,
        sftp_delivery=sftp_delivery,
        as2_delivery=as2_delivery,
        vault=vault,
        field_encryption=field_encryption,
        crypto_service=crypto_service,
    )
    return _build_dispatcher_from_registry(registry, uow_provider)


def _setup_dlq_registry(
    settings: WorkerSettings,
    uow_provider: TenantUoWProviderPort,
    publisher: OutboxPublisherPort | None = None,
) -> EdiDataPlaneEventDispatcher:
    resolved_publisher = publisher or _create_default_publisher(settings)
    registry = _build_dlq_route_registry(publisher=resolved_publisher)
    return _build_dispatcher_from_registry(registry, uow_provider)


class _BaseEdiDeliveryWorkerModule(LaunchableWorker):
    """Shared infrastructure lifecycle for primary and DLQ EDI delivery workers."""

    def __init__(self) -> None:
        self.db_router: DatabaseRouter | None = None
        self.deliver_manager: SqsConsumerManager | None = None
        self.http_delivery: HttpxDeliveryClient | None = None
        self.as2_delivery: HttpxAS2DeliveryClient | None = None

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

        if self.http_delivery:
            try:
                await self.http_delivery.close()
            except Exception as exc:
                logger.error("http_delivery_stop_failed", exc_info=exc)
            finally:
                self.http_delivery = None

        if self.as2_delivery:
            try:
                await self.as2_delivery.close()
            except Exception as exc:
                logger.error("as2_delivery_stop_failed", exc_info=exc)
            finally:
                self.as2_delivery = None

        if self.db_router:
            try:
                await self.db_router.close_all()
            except Exception as exc:
                logger.error("db_router_stop_failed", exc_info=exc)
            finally:
                self.db_router = None


class EdiDeliveryWorkerModule(_BaseEdiDeliveryWorkerModule):
    """Primary EDI outbound delivery worker polling `SQS_DELIVER_QUEUE_URL`."""

    async def start(self) -> None:
        settings = get_settings()
        aws_endpoint = settings.aws.endpoint_url
        s3_bucket = settings.s3.bucket

        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        resolver = SqlAlchemyTenantResolver(self.db_router)
        vault = SecretStoreProvider.get_secret_store(secrets_mount_path=settings.secrets.mount_path)
        field_encryption = SecurityProvider.get_fernet_cipher()
        crypto_service = SmimeCryptoService()

        uow_provider = create_edi_tenant_uow_provider(
            resolver=resolver,
            db_router=self.db_router,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        self.http_delivery = HttpxDeliveryClient(validator=validate_target_url)
        sftp_delivery = ParamikoSftpClient()
        self.as2_delivery = HttpxAS2DeliveryClient(
            validator=partial(validate_target_url, allow_private_ips=settings.allow_private_ips),
            allow_private_ips=settings.allow_private_ips,
        )

        consumer = _setup_registry(
            settings=settings,
            uow_provider=uow_provider,
            http_delivery=self.http_delivery,
            sftp_delivery=sftp_delivery,
            as2_delivery=self.as2_delivery,
            vault=vault,
            field_encryption=field_encryption,
            crypto_service=crypto_service,
        )

        self.deliver_manager = PubSubProvider.create_consumer_manager(
            queue_url=settings.sqs.deliver_queue_url,
            handler=consumer.handle,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        self.deliver_manager.start()


class EdiDeliveryDlqWorkerModule(_BaseEdiDeliveryWorkerModule):
    """Terminal DLQ worker polling `SQS_DELIVER_DLQ_URL` to record permanent delivery failures."""

    async def start(self) -> None:
        settings = get_settings()
        if not settings.sqs.deliver_dlq_url:
            raise ValueError("SQS_DELIVER_DLQ_URL is required when running in DLQ mode")

        aws_endpoint = settings.aws.endpoint_url
        s3_bucket = settings.s3.bucket

        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        resolver = SqlAlchemyTenantResolver(self.db_router)
        uow_provider = create_edi_tenant_uow_provider(
            resolver=resolver,
            db_router=self.db_router,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        consumer = _setup_dlq_registry(settings=settings, uow_provider=uow_provider)
        self.deliver_manager = PubSubProvider.create_consumer_manager(
            queue_url=settings.sqs.deliver_dlq_url,
            handler=consumer.handle,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        self.deliver_manager.start()


def _create_delivery_worker_from_argv(argv: list[str]) -> tuple[str, LaunchableWorker]:
    if "--dlq" in argv:
        return "edi-delivery-dlq-worker", EdiDeliveryDlqWorkerModule()
    return "edi-delivery-worker", EdiDeliveryWorkerModule()


async def main(stop_event: asyncio.Event | None = None) -> None:
    service_name, module = _create_delivery_worker_from_argv(sys.argv[1:])
    ObservabilityProvider.auto_configure_from_env(service_name)
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    service_name, _ = _create_delivery_worker_from_argv(sys.argv[1:])
    ObservabilityProvider.auto_configure_from_env(service_name)
    run_worker_app(lambda: _create_delivery_worker_from_argv(sys.argv[1:])[1])
