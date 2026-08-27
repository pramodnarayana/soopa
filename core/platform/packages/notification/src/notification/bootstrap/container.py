"""
Dependency Injection Container for the Notification Engine.

All top-level imports are resolved here at module load time — no inline imports
inside class bodies. The Container is the single source of truth for all
dependency wiring in this bounded context.
"""

from collections.abc import AsyncGenerator

import structlog
from database.provider import get_async_engine
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from notification.adapters.outbound.channels import (
    EmailDeliveryStrategy,
    InAppDeliveryStrategy,
    SlackDeliveryStrategy,
)
from notification.adapters.outbound.channels.dummy_email_provider import DummyEmailProvider
from notification.adapters.outbound.database.postgres_notification_query_repository import (
    SqlAlchemyNotificationQueryRepository,
)
from notification.adapters.outbound.database.uow import SqlAlchemyNotificationUnitOfWork
from notification.adapters.outbound.delivery_dispatcher import NotificationDeliveryDispatcher
from notification.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.application.update_user_preference_use_case import (
    UpdateUserPreferenceUseCase,
)
from notification.config import NotificationEngineSettings

logger = structlog.get_logger(__name__)


async def _init_async_engine(database_url: str) -> AsyncGenerator[AsyncEngine]:
    """Resource lifecycle hook: creates and disposes the SQLAlchemy async engine."""
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = get_async_engine(database_url)
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

    # -----------------------------------------------------------------------
    # Unit of Work
    # -----------------------------------------------------------------------

    uow = providers.Factory(
        SqlAlchemyNotificationUnitOfWork,
        session=session_factory.provided(),
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

    notification_compiler = providers.Factory(
        NotificationCompilerUseCase,
        uow=uow,
        template_renderer=template_renderer,
    )

    update_user_preference_use_case = providers.Factory(
        UpdateUserPreferenceUseCase,
        uow=uow,
    )

    get_user_preferences_use_case = providers.Factory(
        GetUserPreferencesUseCase,
        uow=uow,
    )

    # -----------------------------------------------------------------------
    # We don't inject outbox_sweeper_use_case here because we don't have
    # the outbox repository in this container anymore (it's inside UoW).
    # The worker container should redefine it by injecting a raw
    # OutboxRepositoryPort if needed for the sweeper, or the sweeper
    # should be refactored to use UoW. We remove it from here for now.
    # -----------------------------------------------------------------------
