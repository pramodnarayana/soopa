from database.provider import get_async_engine
from dependency_injector import containers, providers
from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.tenant_query_service import DatabaseTenantQueryService
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.api_tokens import (
    CreateApiTokenUseCase,
    DeleteApiTokenUseCase,
    ListApiTokensUseCase,
    UpdateApiTokenUseCase,
)
from ucp.application.use_cases.create_user_use_case import CreateUserUseCase
from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.application.use_cases.delete_user_use_case import DeleteUserUseCase
from ucp.application.use_cases.provision_tenant_use_case import ProvisionTenantUseCase
from ucp.application.use_cases.subscribe_app_use_case import SubscribeAppUseCase
from ucp.application.use_cases.toggle_tenant_status_use_case import ToggleTenantStatusUseCase
from ucp.application.use_cases.toggle_user_status_use_case import ToggleUserStatusUseCase
from ucp.application.use_cases.unsubscribe_app_use_case import UnsubscribeAppUseCase
from ucp.application.use_cases.update_tenant_name_use_case import UpdateTenantNameUseCase
from ucp.application.use_cases.update_user_use_case import UpdateUserUseCase
from ucp.application.use_cases.webhooks import (
    CreateWebhookUseCase,
    DeleteWebhookUseCase,
    ListWebhooksUseCase,
    UpdateWebhookUseCase,
)
from ucp.bootstrap.config import get_settings

_settings = get_settings()
_engine = get_async_engine(_settings.database_url)
_async_session_maker = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the UCP bounded context.
    """

    wiring_config = containers.WiringConfiguration(
        packages=[
            "unified_api.adapters.inbound.http.routers",
            "unified_api.adapters.inbound.http.guards",
        ]
    )

    # -----------------------------------------------------------------------
    # Database Repositories (Session provided at runtime via kwargs)
    # -----------------------------------------------------------------------
    tenant_repo = providers.Factory(TenantRepository)
    tenant_query_service = providers.Factory(DatabaseTenantQueryService)
    app_repo = providers.Factory(PostgresAppRepository)
    user_repo = providers.Factory(PostgresUserRepository)
    api_token_repo = providers.Factory(PostgresApiTokenRepository)
    role_repo = providers.Factory(PostgresRoleRepository)
    session_factory_provider = providers.Object(_async_session_maker)
    outbox_repo = providers.Factory(
        PostgresOutboxRepository, session_factory=session_factory_provider
    )

    # -----------------------------------------------------------------------
    # Unit Of Work (Session provided at runtime via kwargs)
    # -----------------------------------------------------------------------
    uow = providers.Factory(SqlAlchemyUcpUnitOfWork)

    # -----------------------------------------------------------------------
    # Services & Use Cases
    # -----------------------------------------------------------------------
    create_api_token_use_case = providers.Factory(
        CreateApiTokenUseCase,
        uow=uow,
    )

    update_api_token_use_case = providers.Factory(
        UpdateApiTokenUseCase,
        uow=uow,
    )

    list_api_tokens_use_case = providers.Factory(
        ListApiTokensUseCase,
        uow=uow,
    )

    delete_api_token_use_case = providers.Factory(
        DeleteApiTokenUseCase,
        uow=uow,
    )

    provision_tenant_use_case = providers.Factory(
        ProvisionTenantUseCase,
        uow=uow,
    )

    delete_tenant_use_case = providers.Factory(
        DeleteTenantUseCase,
        uow=uow,
    )

    update_tenant_name_use_case = providers.Factory(
        UpdateTenantNameUseCase,
        uow=uow,
    )

    toggle_tenant_status_use_case = providers.Factory(
        ToggleTenantStatusUseCase,
        uow=uow,
    )

    subscribe_app_use_case = providers.Factory(
        SubscribeAppUseCase,
        uow=uow,
    )

    unsubscribe_app_use_case = providers.Factory(
        UnsubscribeAppUseCase,
        uow=uow,
    )

    create_user_use_case = providers.Factory(
        CreateUserUseCase,
        uow=uow,
    )

    update_user_use_case = providers.Factory(
        UpdateUserUseCase,
        uow=uow,
    )

    toggle_user_status_use_case = providers.Factory(
        ToggleUserStatusUseCase,
        uow=uow,
    )

    delete_user_use_case = providers.Factory(
        DeleteUserUseCase,
        uow=uow,
    )

    create_webhook_use_case = providers.Factory(
        CreateWebhookUseCase,
        uow=uow,
    )

    update_webhook_use_case = providers.Factory(
        UpdateWebhookUseCase,
        uow=uow,
    )

    list_webhooks_use_case = providers.Factory(
        ListWebhooksUseCase,
        uow=uow,
    )

    delete_webhook_use_case = providers.Factory(
        DeleteWebhookUseCase,
        uow=uow,
    )
