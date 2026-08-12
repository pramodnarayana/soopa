"""
Dependency Injection Container for the Notification Engine.

All top-level imports are resolved here at module load time — no inline imports
inside class bodies. The Container is the single source of truth for all
dependency wiring in this bounded context.
"""

import logging
from collections.abc import AsyncGenerator

from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from notification_engine.adapters.inbound.postgres_listener import PostgresNotificationListener
from notification_engine.adapters.outbound.channels import (
    EmailDeliveryStrategy,
    InAppDeliveryStrategy,
    SlackDeliveryStrategy,
)
from notification_engine.adapters.outbound.delivery_dispatcher import StrategyDeliveryDispatcher
from notification_engine.adapters.outbound.postgres_in_app_persistence import (
    PostgresInAppPersistence,
)
from notification_engine.adapters.outbound.postgres_notification_query_repository import (
    PostgresNotificationQueryRepository,
)
from notification_engine.adapters.outbound.postgres_outbox_repository import (
    PostgresOutboxRepository,
)
from notification_engine.adapters.outbound.postgres_route_repository import PostgresRouteRepository
from notification_engine.adapters.outbound.postgres_template_repository import (
    PostgresTemplateRepository,
)
from notification_engine.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification_engine.application.consumer import NotificationConsumerWorker
from notification_engine.application.dispatch_use_case import DispatchNotificationUseCase
from notification_engine.application.outbox_sweeper import NotificationOutboxSweeper
from notification_engine.application.stream_manager import NotificationStreamManager
from notification_engine.config import NotificationEngineSettings

logger = logging.getLogger(__name__)


async def _init_async_engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    """Resource lifecycle hook: creates and disposes the SQLAlchemy async engine."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()
        logger.info("Database engine disposed by DI container.")


def _init_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the Notification Engine bounded context.

    Wiring rules:
    - Infrastructure (engine, session_factory): Resource / Singleton — one per process lifetime.
    - Stateless services (renderer): Singleton — one shared instance, no allocation cost per request.
    - Repositories: Factory — new per request to avoid shared session state.
    - Workers: Factory — created once by the lifespan, not per-request.
    """

    config = providers.Configuration()

    # -----------------------------------------------------------------------
    # Infrastructure — one per process
    # -----------------------------------------------------------------------

    engine = providers.Resource(
        _init_async_engine,
        database_url=config.database_url,
    )

    session_factory = providers.Singleton(
        _init_session_factory,
        engine=engine,
    )

    # -----------------------------------------------------------------------
    # Stateless services — Singleton: constructed once, reused for every request.
    # Jinja2 SandboxedEnvironment compilation is expensive; Singleton avoids
    # re-compiling on every render call.
    # -----------------------------------------------------------------------

    template_renderer = providers.Singleton(
        Jinja2TemplateRenderer,
    )

    engine_settings = providers.Singleton(
        NotificationEngineSettings,
    )

    stream_manager = providers.Singleton(
        NotificationStreamManager,
    )

    postgres_listener = providers.Singleton(
        PostgresNotificationListener,
        database_url=config.database_url,
        stream_manager=stream_manager,
    )

    # -----------------------------------------------------------------------
    # Repositories — Factory: new instance per request.
    #
    # Segregated by Aggregate Root (DDD):
    #   - PostgresTemplateRepository: Template aggregate (dispatch read + API CRUD)
    #   - PostgresRouteRepository: Routing aggregate (dispatch read + API CRUD)
    # -----------------------------------------------------------------------

    template_repository = providers.Factory(
        PostgresTemplateRepository,
        session_factory=session_factory,
    )

    route_repository = providers.Factory(
        PostgresRouteRepository,
        session_factory=session_factory,
    )

    in_app_persistence = providers.Factory(
        PostgresInAppPersistence,
        session_factory=session_factory,
    )

    outbox_repository = providers.Factory(
        PostgresOutboxRepository,
        session_factory=session_factory,
    )

    query_repository = providers.Factory(
        PostgresNotificationQueryRepository,
        session_factory=session_factory,
    )

    # -----------------------------------------------------------------------
    # Delivery Strategies — pure delivery adapters; rendering is upstream.
    # -----------------------------------------------------------------------

    email_strategy = providers.Factory(
        EmailDeliveryStrategy,
    )

    in_app_strategy = providers.Factory(
        InAppDeliveryStrategy,
        persistence=in_app_persistence,
    )

    slack_strategy = providers.Factory(
        SlackDeliveryStrategy,
    )

    delivery_dispatcher = providers.Factory(
        StrategyDeliveryDispatcher,
        email_strategy=email_strategy,
        in_app_strategy=in_app_strategy,
        slack_strategy=slack_strategy,
    )

    # -----------------------------------------------------------------------
    # Use Cases
    # -----------------------------------------------------------------------

    dispatch_use_case = providers.Factory(
        DispatchNotificationUseCase,
        template_repo=template_repository,
        template_renderer=template_renderer,
        outbox_repo=outbox_repository,
        route_repo=route_repository,
    )

    # -----------------------------------------------------------------------
    # Workers — created once at lifespan startup.
    # -----------------------------------------------------------------------

    consumer_worker = providers.Factory(
        NotificationConsumerWorker,
        dispatch_use_case=dispatch_use_case,
    )

    sweeper_worker = providers.Factory(
        NotificationOutboxSweeper,
        repository=outbox_repository,
        dispatcher=delivery_dispatcher,
        poll_interval_seconds=config.poll_interval,
    )
