"""
UCP Domain Startup and Shutdown Hooks.

These are pure async functions that start and stop UCP background workers.
They accept NO ``app`` parameter — UCP domain workers must not hold a reference
to the Shell application instance.

Architecture note:
  - These hooks are called by the Shell's lifespan (unified_api/bootstrap/lifespan.py).
  - The Shell owns the lifecycle; UCP exposes discrete start/stop operations.
  - This follows the Dependency Inversion Principle: the Shell depends on UCP's
    hooks, but UCP does not depend on (or know about) the Shell.
"""

import os
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ucp.adapters.inbound.sqs_ucp_event_listener import SqsUcpEventListener
from ucp.adapters.inbound.workers.outbox_relay import ControlPlaneOutboxRelay
from ucp.adapters.inbound.workers.outbox_sweeper import ControlPlaneOutboxSweeper
from ucp.adapters.inbound.workers.sqs_event_dispatcher import SqsEventDispatcherWorker
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.identity.dummy_identity_provider import DummyIdentityProvider
from ucp.adapters.outbound.identity.zitadel_identity_provider import ZitadelIdentityProvider
from ucp.adapters.outbound.messaging.sns_outbox_publisher import SnsOutboxPublisher
from ucp.application.services.identity_sync_service import IdentitySyncService
from ucp.application.services.infrastructure_provisioner import InfrastructureProvisioner
from ucp.bootstrap.container import Container
from ucp.core.config import get_settings
from ucp.ports.identity_provider import IdentityProviderPort
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider

settings = get_settings()
logger = structlog.get_logger(__name__)

# Module-level references held during the process lifetime.
# These are initialized by ``startup()`` and released by ``shutdown()``.
_relay: ControlPlaneOutboxRelay | None = None
_sweeper: ControlPlaneOutboxSweeper | None = None
_dispatcher: SqsEventDispatcherWorker | None = None
_identity_service: IdentitySyncService | None = None
_provisioner: InfrastructureProvisioner | None = None
_engine = None


async def startup() -> None:  # noqa: C901
    """
    Starts all UCP background workers.
    Called by the Shell lifespan on application startup.
    """
    global _relay, _sweeper, _dispatcher, _identity_service, _provisioner, _engine

    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if not database_url:
        logger.warning("database_url_not_set_workers_not_starting")
        return

    _engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

    _repository = PostgresOutboxRepository(session_factory)

    relay_publisher = SnsOutboxPublisher(
        topic_arn=settings.sns_tenant_events_topic_arn,
        endpoint_url=settings.aws_endpoint_url,
    )
    _relay = ControlPlaneOutboxRelay(
        repository=_repository,
        publisher=relay_publisher,
        database_url=database_url,
    )
    _relay.start()
    logger.info("ucp_outbox_relay_started")

    sweeper_publisher = SnsOutboxPublisher(
        topic_arn=settings.sns_tenant_events_topic_arn,
        endpoint_url=settings.aws_endpoint_url,
    )
    _sweeper = ControlPlaneOutboxSweeper(
        repository=_repository,
        publisher=sweeper_publisher,
        poll_interval_seconds=int(os.environ.get("OUTBOX_POLL_INTERVAL_SECONDS", "5")),
    )
    _sweeper.start()
    logger.info("ucp_outbox_sweeper_started")

    container = Container()
    idp: IdentityProviderPort
    idp_users: IUserIdentityProvider

    if os.environ.get("APP_ENV", "production") in ("local", "test"):
        idp = DummyIdentityProvider()
        idp_users = DummyIdentityProvider()  # type: ignore
    else:
        idp = ZitadelIdentityProvider(org_provider=container.org_provider())
        idp_users = container.user_provider()

    _identity_service = IdentitySyncService(identity_provider=idp, user_identity_provider=idp_users)
    _provisioner = InfrastructureProvisioner(session_factory)

    _dispatcher = SqsEventDispatcherWorker(
        event_listener=SqsUcpEventListener(
            queue_url=settings.sqs_ucp_events_queue_url,
            endpoint_url=settings.aws_endpoint_url,
        )
    )

    # Register all pure business handlers
    _dispatcher.subscribe("app.subscribed", _provisioner.handle_app_subscribed)
    _dispatcher.subscribe("app.unsubscribed", _provisioner.handle_app_unsubscribed)

    # Notice how we can map multiple handlers, or handle different events cleanly
    async def identity_tenant_provisioned_handler(event: Any) -> None:
        service = _identity_service
        if service:
            await service.handle_tenant_provisioned(event.tenant_id)

    async def identity_user_created_handler(event: Any) -> None:
        service = _identity_service
        if service:
            payload = event.payload
            await service.handle_user_created(
                org_id=payload["org_id"],
                email=payload["email"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                role=payload["role"],
            )

    async def identity_user_updated_handler(event: Any) -> None:
        service = _identity_service
        if service:
            payload = event.payload
            await service.handle_user_updated(
                idp_user_id=payload["idp_user_id"],
                org_id=payload["org_id"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                role=payload["role"],
            )

    async def identity_user_status_toggled_handler(event: Any) -> None:
        service = _identity_service
        if service:
            payload = event.payload
            await service.handle_user_status_toggled(
                idp_user_id=payload["idp_user_id"],
                org_id=payload["org_id"],
                action=payload["action"],
            )

    async def identity_user_deleted_handler(event: Any) -> None:
        service = _identity_service
        if service:
            payload = event.payload
            await service.handle_user_deleted(idp_user_id=payload["idp_user_id"])

    # Use exact event names matching domain event `event_name` properties
    _dispatcher.subscribe("tenant.provisioned", identity_tenant_provisioned_handler)
    _dispatcher.subscribe("UserInvited", identity_user_created_handler)
    _dispatcher.subscribe("UserUpdated", identity_user_updated_handler)
    _dispatcher.subscribe("UserStatusToggled", identity_user_status_toggled_handler)
    _dispatcher.subscribe("UserDeleted", identity_user_deleted_handler)

    _dispatcher.start()
    logger.info("sqs_event_dispatcher_started")


async def shutdown() -> None:
    """
    Gracefully stops all UCP background workers.
    Called by the Shell lifespan on application shutdown.
    """
    global _relay, _sweeper, _dispatcher, _identity_service, _provisioner, _engine

    if _relay:
        await _relay.stop()
        logger.info("ucp_outbox_relay_stopped")
        _relay = None

    if _sweeper:
        await _sweeper.stop()
        logger.info("ucp_outbox_sweeper_stopped")
        _sweeper = None

    if _dispatcher:
        await _dispatcher.stop()
        logger.info("sqs_event_dispatcher_stopped")
        _dispatcher = None

    _identity_service = None
    _provisioner = None

    if _engine:
        await _engine.dispose()
        _engine = None


from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await startup()
    yield
    await shutdown()
