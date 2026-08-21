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

from notification.adapters.outbound.channels import (
    EmailDeliveryStrategy,
    InAppDeliveryStrategy,
    SlackDeliveryStrategy,
)
from notification.adapters.outbound.channels.dummy_email_provider import DummyEmailProvider
from notification.adapters.outbound.database.postgres_in_app_persistence import (
    SqlAlchemyInAppPersistence,
)
from notification.adapters.outbound.database.postgres_notification_query_repository import (
    SqlAlchemyNotificationQueryRepository,
)
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.adapters.outbound.database.postgres_route_repository import (
    SqlAlchemyNotificationRouteRepository,
)
from notification.adapters.outbound.database.postgres_template_repository import (
    SqlAlchemyTemplateRepository,
)
from notification.adapters.outbound.database.postgres_user_preference_repository import (
    SqlAlchemyUserNotificationPreferenceRepository,
)
from notification.adapters.outbound.delivery_dispatcher import NotificationDeliveryDispatcher
from notification.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification.application.dispatch_use_case import DispatchNotificationUseCase
from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
from notification.application.notification_outbox_processor_use_case import (
    NotificationOutboxProcessorUseCase,
)
from notification.application.notification_outbox_sweeper_use_case import (
    NotificationOutboxSweeperUseCase,
)
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

    # -----------------------------------------------------------------------
    # Repositories — Factory: new instance per request.
    #
    # Segregated by Aggregate Root (DDD):
    #   - SqlAlchemyTemplateRepository: Template aggregate (dispatch read + API CRUD)
    #   - SqlAlchemyNotificationRouteRepository: Routing aggregate (dispatch read + API CRUD)
    # -----------------------------------------------------------------------

    template_repository = providers.Factory(
        SqlAlchemyTemplateRepository,
        session_factory=session_factory,
    )

    route_repository = providers.Factory(
        SqlAlchemyNotificationRouteRepository,
        session_factory=session_factory,
    )

    in_app_persistence = providers.Factory(
        SqlAlchemyInAppPersistence,
        session_factory=session_factory,
    )

    outbox_repository = providers.Factory(
        SqlAlchemyNotificationOutboxRepository,
        session_factory=session_factory,
    )

    user_preference_repository = providers.Factory(
        SqlAlchemyUserNotificationPreferenceRepository,
        session_factory=session_factory,
    )

    query_repository = providers.Factory(
        SqlAlchemyNotificationQueryRepository,
        session_factory=session_factory,
    )

    # -----------------------------------------------------------------------
    # Delivery Strategies — pure delivery adapters; rendering is upstream.
    # -----------------------------------------------------------------------

    email_provider = providers.Factory(
        DummyEmailProvider,
    )

    email_strategy = providers.Factory(
        EmailDeliveryStrategy,
        email_provider=email_provider,
    )

    in_app_strategy = providers.Factory(
        InAppDeliveryStrategy,
        persistence=in_app_persistence,
    )

    slack_strategy = providers.Factory(
        SlackDeliveryStrategy,
    )

    delivery_dispatcher = providers.Factory(
        NotificationDeliveryDispatcher,
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

    get_user_preferences_use_case = providers.Factory(
        GetUserPreferencesUseCase,
        repository=user_preference_repository,
    )

    sweep_outbox_use_case = providers.Factory(
        NotificationOutboxSweeperUseCase,
        repository=outbox_repository,
    )

    outbox_processor = providers.Singleton(
        NotificationOutboxProcessorUseCase,
        repository=outbox_repository,
        dispatcher=delivery_dispatcher,
    )
