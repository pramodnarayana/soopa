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

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ucp.adapters.inbound.sqs_ucp_event_listener import SqsUcpEventListener
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.identity.dummy_identity_provider import DummyIdentityProvider
from ucp.adapters.outbound.identity.zitadel_identity_provider import ZitadelIdentityProvider
from ucp.adapters.outbound.messaging.sns_outbox_publisher import SnsOutboxPublisher
from ucp.application.services.identity_sync_service import IdentitySyncService
from ucp.application.services.infrastructure_provisioner import InfrastructureProvisioner
from ucp.application.workers.event_listener import ControlPlaneEventListener
from ucp.application.workers.outbox_sweeper import ControlPlaneOutboxSweeper
from ucp.bootstrap.container import Container
from ucp.core.config import get_settings
from ucp.ports.identity_provider import IdentityProviderPort

settings = get_settings()
logger = structlog.get_logger(__name__)

# Module-level references held during the process lifetime.
# These are initialized by ``startup()`` and released by ``shutdown()``.
_sweeper: ControlPlaneOutboxSweeper | None = None
_listener: ControlPlaneEventListener | None = None
_identity_service: IdentitySyncService | None = None
_engine = None


async def startup() -> None:
    """
    Starts all UCP background workers.
    Called by the Shell lifespan on application startup.
    """
    global _sweeper, _listener, _identity_service, _engine

    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if not database_url:
        logger.warning("database_url_not_set_workers_not_starting")
        return

    _engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

    _sweeper = ControlPlaneOutboxSweeper(
        repository=PostgresOutboxRepository(session_factory),
        publisher=SnsOutboxPublisher(
            topic_arn=settings.sns_tenant_events_topic_arn,
            endpoint_url=settings.aws_endpoint_url,
        ),
        database_url=database_url,
        poll_interval_seconds=int(os.environ.get("OUTBOX_POLL_INTERVAL_SECONDS", "5")),
    )
    _sweeper.start()
    logger.info("ucp_outbox_sweeper_started")

    idp: IdentityProviderPort
    if os.environ.get("APP_ENV", "production") in ("local", "test"):
        idp = DummyIdentityProvider()
    else:
        container = Container()
        idp = ZitadelIdentityProvider(org_provider=container.org_provider())

    _identity_service = IdentitySyncService(
        event_listener=SqsUcpEventListener(
            queue_url=settings.sqs_ucp_events_queue_url,
            endpoint_url=settings.aws_endpoint_url,
        ),
        identity_provider=idp,
    )
    _identity_service.start()

    _listener = ControlPlaneEventListener(database_url)
    provisioner = InfrastructureProvisioner(session_factory)
    _listener.subscribe("app.subscribed", provisioner.handle_app_subscribed)
    _listener.subscribe("app.unsubscribed", provisioner.handle_app_unsubscribed)
    _listener.start()
    logger.info("ucp_event_listener_started")


async def shutdown() -> None:
    """
    Gracefully stops all UCP background workers.
    Called by the Shell lifespan on application shutdown.
    """
    global _sweeper, _listener, _identity_service, _engine

    if _sweeper:
        await _sweeper.stop()
        logger.info("ucp_outbox_sweeper_stopped")
        _sweeper = None

    if _identity_service:
        await _identity_service.stop()
        logger.info("ucp_identity_sync_service_stopped")
        _identity_service = None

    if _listener:
        await _listener.stop()
        logger.info("ucp_event_listener_stopped")
        _listener = None

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
