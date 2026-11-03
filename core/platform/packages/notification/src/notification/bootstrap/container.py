"""
Dependency Injection Container for the Notification Engine.

All top-level imports are resolved here at module load time — no inline imports
inside class bodies. The Container is the single source of truth for all
dependency wiring in this bounded context.
"""

from collections.abc import AsyncGenerator, Callable

import structlog
from database.provider import DatabaseProvider
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from notification.adapters.outbound.channel_dispatcher import NotificationChannelDispatcher
from notification.adapters.outbound.channels import (
    EmailChannelStrategy,
    InAppChannelStrategy,
    SlackChannelStrategy,
)
from notification.adapters.outbound.channels.dummy_email_provider import DummyEmailProvider
from notification.adapters.outbound.database.sqlalchemy_notification_query_repository import (
    SqlAlchemyNotificationQueryRepository,
)
from notification.adapters.outbound.database.sqlalchemy_notification_record_repository import (
    SqlAlchemyNotificationRecordRepository,
)
from notification.adapters.outbound.database.sqlalchemy_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.adapters.outbound.database.sqlalchemy_route_repository import (
    SqlAlchemyNotificationRouteRepository,
)
from notification.adapters.outbound.database.sqlalchemy_template_repository import (
    SqlAlchemyTemplateRepository,
)
from notification.adapters.outbound.database.sqlalchemy_user_preference_repository import (
    SqlAlchemyUserNotificationPreferenceRepository,
)
from notification.adapters.outbound.database.uow import SqlAlchemyNotificationUnitOfWork
from notification.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.application.update_user_preference_use_case import (
    UpdateUserPreferenceUseCase,
)
from notification.config import NotificationEngineSettings

logger = structlog.get_logger(__name__)


async def _init_db_provider(database_url: str) -> AsyncGenerator[DatabaseProvider]:
    """Resource lifecycle hook: creates and disposes the centralized DatabaseProvider."""
    provider = DatabaseProvider.from_url(database_url)
    try:
        yield provider
    finally:
        await provider.close()
        logger.info("database_provider_disposed")


def _extract_session_factory(provider: DatabaseProvider) -> Callable[[], AsyncSession]:
    return provider.session_factory


def create_notification_uow(session: AsyncSession) -> SqlAlchemyNotificationUnitOfWork:
    """Composition Root factory assembling concrete Notification repositories into SqlAlchemyNotificationUnitOfWork."""
    return SqlAlchemyNotificationUnitOfWork(
        session=session,
        user_preference_repo=SqlAlchemyUserNotificationPreferenceRepository(session=session),
        template_repo=SqlAlchemyTemplateRepository(session=session),
        record_repo=SqlAlchemyNotificationRecordRepository(session=session),
        route_repo=SqlAlchemyNotificationRouteRepository(session=session),
        outbox_repo=SqlAlchemyNotificationOutboxRepository(session=session),
    )


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

    db_provider = providers.Resource(
        _init_db_provider,
        database_url=config.database_url,
    )

    session_factory = providers.Callable(
        _extract_session_factory,
        provider=db_provider,
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
        create_notification_uow,
        session=session_factory.provided.call(),
    )

    query_repository = providers.Factory(
        SqlAlchemyNotificationQueryRepository,
        session_factory=session_factory,
    )

    template_repository = providers.Factory(
        SqlAlchemyTemplateRepository,
        session=session_factory.provided.call(),
    )

    route_repository = providers.Factory(
        SqlAlchemyNotificationRouteRepository,
        session=session_factory.provided.call(),
    )

    # -----------------------------------------------------------------------
    # Delivery Strategies — pure delivery adapters; rendering is upstream.
    # -----------------------------------------------------------------------

    email_provider = providers.Factory(
        DummyEmailProvider,
    )

    email_strategy = providers.Factory(
        EmailChannelStrategy,
        email_provider=email_provider,
    )

    in_app_strategy = providers.Factory(
        InAppChannelStrategy,
    )

    slack_strategy = providers.Factory(
        SlackChannelStrategy,
    )

    channel_dispatcher = providers.Factory(
        NotificationChannelDispatcher,
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
