"""
Dependency Injection Container for the Notification Engine.

All top-level imports are resolved here at module load time — no inline imports
inside class bodies. The Container is the single source of truth for all
dependency wiring in this bounded context.
"""

from collections.abc import AsyncGenerator

import structlog
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from notification.adapters.inbound.jobs.outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification.adapters.inbound.notification_outbox_relay import NotificationOutboxRelay
from notification.adapters.inbound.postgres_listener import PostgresNotificationListener
from notification.adapters.outbound.channels import (
    EmailDeliveryStrategy,
    InAppDeliveryStrategy,
    SlackDeliveryStrategy,
)
from notification.adapters.outbound.delivery_dispatcher import StrategyDeliveryDispatcher
from notification.adapters.outbound.postgres_in_app_persistence import (
    PostgresInAppPersistence,
)
from notification.adapters.outbound.postgres_notification_query_repository import (
    PostgresNotificationQueryRepository,
)
from notification.adapters.outbound.postgres_outbox_repository import (
    PostgresOutboxRepository,
)
from notification.adapters.outbound.postgres_route_repository import PostgresRouteRepository
from notification.adapters.outbound.postgres_template_repository import (
    PostgresTemplateRepository,
)
from notification.adapters.outbound.postgres_user_preference_repository import (
    PostgresUserNotificationPreferenceRepository,
)
from notification.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification.application.consumer import NotificationConsumerWorker
from notification.application.dispatch_use_case import DispatchNotificationUseCase
from notification.application.outbox_processor import NotificationOutboxProcessor
from notification.application.stream_manager import NotificationStreamManager
from notification.application.sweep_outbox_use_case import SweepNotificationOutboxUseCase
from notification.application.update_user_preference_use_case import (
    UpdateUserPreferenceUseCase,
)
from notification.config import NotificationEngineSettings

logger = structlog.get_logger(__name__)


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
    # The Singleton prevents re-creating the Jinja2 SandboxedEnvironment on every
    # request; template compilation itself is cached by the renderer's internal LRU cache.
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

    user_preference_repository = providers.Factory(
        PostgresUserNotificationPreferenceRepository,
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
        user_pref_repo=user_preference_repository,
    )

    update_user_preference_use_case = providers.Factory(
        UpdateUserPreferenceUseCase,
        repo=user_preference_repository,
    )

    # -----------------------------------------------------------------------
    # Workers — created once at lifespan startup.
    # Use Singleton so repeated resolutions reuse the same lifespan-owned instances.
    # -----------------------------------------------------------------------

    outbox_processor = providers.Singleton(
        NotificationOutboxProcessor,
        repository=outbox_repository,
        dispatcher=delivery_dispatcher,
    )

    outbox_listener = providers.Singleton(
        NotificationOutboxRelay,
        processor=outbox_processor,
        database_url=config.database_url,
    )

    sweep_outbox_use_case = providers.Factory(
        SweepNotificationOutboxUseCase,
        repository=outbox_repository,
    )

    sweeper_worker = providers.Singleton(
        NotificationOutboxSweeperJobHandler,
        use_case=sweep_outbox_use_case,
    )

    consumer_worker = providers.Singleton(
        NotificationConsumerWorker,
        dispatch_use_case=dispatch_use_case,
        sweeper_job_handler=sweeper_worker,
    )
