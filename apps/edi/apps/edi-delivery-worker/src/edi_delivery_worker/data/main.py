import asyncio
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import Any

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
from edi.adapters.outbound.security.network import validate_target_url
from edi.application.use_cases.pipeline.execute_delivery_use_case import (
    ExecuteDeliveryCommand,
    ExecuteDeliveryUseCase,
)
from edi.config.settings import AppSettings, get_settings
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.enums import PipelineEventType
from edi.domain.exceptions import InvalidMessageError
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from secret_store.ports.secret_store_port import SecretStorePort

from edi_delivery_worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from edi_delivery_worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry

UowFactory = Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]

load_dotenv()
logger = structlog.get_logger(__name__)


def _setup_registry(
    settings: AppSettings,
    uow_provider: TenantUowProvider,
    http_delivery: HttpDeliveryPort,
    sftp_delivery: SftpDeliveryPort,
    as2_delivery: AS2DeliveryPort,
    vault: SecretStorePort,
) -> EdiDataPlaneEventDispatcher:

    registry = EdiDataPlaneRouteRegistry()

    def use_case_factory(uow_fact: UowFactory) -> ExecuteDeliveryUseCase:
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(uow_fact, http_delivery, vault),
            "sftp_partner_id": SftpDeliveryStrategy(uow_fact, sftp_delivery, vault, db_encryption),
            "as2_partner_id": As2DeliveryStrategy(uow_fact, as2_delivery, vault),
        }
        return ExecuteDeliveryUseCase(uow_factory=uow_fact, strategies=strategies)

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        try:
            payload_tenant_id = e.payload["tenant_id"]
            if payload_tenant_id != e.tenant_id:
                raise InvalidMessageError(
                    f"Tenant ID mismatch: event tenant_id {e.tenant_id} != payload tenant_id {payload_tenant_id}"
                )

            command = ExecuteDeliveryCommand(
                trace_id=e.payload["trace_id"],
                tenant_id=e.tenant_id,
                partner_id=e.payload["partner_id"],
                strategy_type=e.payload["strategy_type"],
            )
        except KeyError as exc:
            raise InvalidMessageError(
                f"EXECUTE_DELIVERY_COMMAND payload is missing required field: {exc}"
            ) from exc

        await use_case_factory(uow_fact).execute(command=command, idempotency_key=e.idempotency_key)

    # Note: EXECUTE_DELIVERY_COMMAND is the only event this worker listens to
    registry.register(
        event_type=PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
        direction=None,
        factory=run_deliver,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        await registry.route(event, uow_factory)

    return EdiDataPlaneEventDispatcher(callback=route_event)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = settings.s3.bucket

    db_router = DatabaseRouter(
        global_db_url=settings.database.global_url,
        shard_overrides=settings.database.shard_overrides,
    )
    resolver = TenantResolver(db_router)

    vault = AwsSecretsManagerAdapter(secrets_mount_path=settings.secrets.mount_path)

    uow_provider = TenantUowProvider(
        resolver=resolver,
        db_router=db_router,
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
        settings, uow_provider, http_delivery, sftp_delivery, as2_delivery, vault
    )

    deliver_consumer = AwsSqsConsumer(
        queue_url=settings.sqs.deliver_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=aws_endpoint,
    )
    deliver_manager = SqsConsumerManager(
        consumer=deliver_consumer,
        queue_name=settings.sqs.deliver_queue_url.rsplit("/", 1)[-1],
        handler=consumer.handle,
    )
    deliver_manager.start()

    stop_event = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        tasks_to_wait: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]

        task = getattr(deliver_manager, "task", getattr(deliver_manager, "_task", None))
        if task:
            tasks_to_wait.append(task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not tasks_to_wait[0] and task.exception():
                exc = task.exception()
                logger.error("sqs_consumer_manager_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        logger.info("data_edi_delivery_worker.shutting_down_gracefully")
        results = await asyncio.gather(
            deliver_manager.stop(),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                logger.error("manager_stop_failed", exc_info=res)

        await db_router.close_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        if e.__class__.__name__ == "ValidationError":
            from pydantic import ValidationError

            all_errors = e.errors() if isinstance(e, ValidationError) else []

            missing_fields = [
                f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
                for err in all_errors
                if err.get("type") in ("missing", "value_error.missing")
            ]
            invalid_fields = [
                f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
                for err in all_errors
                if err.get("type") not in ("missing", "value_error.missing")
            ]

            if missing_fields:
                logger.exception(
                    "worker_startup_configuration_error",
                    reason="One or more required environment variables are missing from your .env file.",
                    missing_fields=missing_fields,
                    invalid_fields=invalid_fields,
                )
            else:
                logger.exception(
                    "worker_startup_configuration_error",
                    reason="One or more configuration variables have invalid values.",
                    invalid_fields=invalid_fields,
                )
        else:
            logger.exception("worker_startup_failed")
        raise
