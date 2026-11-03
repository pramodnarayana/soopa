from database.provider import DatabaseProvider
from dependency_injector import containers, providers
from identity.adapters.outbound.database.api_token_repository import SqlAlchemyApiTokenRepository
from identity.adapters.outbound.database.role_repository import SqlAlchemyRoleRepository
from identity.adapters.outbound.database.user_repository import SqlAlchemyUserRepository
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import UcpOutbox

from ucp.adapters.outbound.database.app_repository import SqlAlchemyAppRepository
from ucp.adapters.outbound.database.idempotency_repository import SqlAlchemyIdempotencyRepository
from ucp.adapters.outbound.database.tenant_query_service import SqlAlchemyTenantQueryService
from ucp.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.adapters.outbound.database.webhook_repository import SqlAlchemyWebhookRepository
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
from ucp.domain.constants import UcpOutboxSource


def create_ucp_uow(session: AsyncSession) -> SqlAlchemyUcpUnitOfWork:
    """Composition root factory assembling SqlAlchemyUcpUnitOfWork with concrete repositories."""
    return SqlAlchemyUcpUnitOfWork(
        session,
        tenant_repo=SqlAlchemyTenantRepository(session=session),
        user_repo=SqlAlchemyUserRepository(session=session),
        api_token_repo=SqlAlchemyApiTokenRepository(session=session),
        app_repo=SqlAlchemyAppRepository(session=session),
        role_repo=SqlAlchemyRoleRepository(session=session),
        webhook_repo=SqlAlchemyWebhookRepository(session=session),
        idempotency_repo=SqlAlchemyIdempotencyRepository(session=session),
    )


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the UCP bounded context.
    """

    config = providers.Configuration()
    db_provider = providers.Dependency(instance_of=DatabaseProvider)

    wiring_config = containers.WiringConfiguration(
        packages=[
            "unified_api.adapters.inbound.http.ucp.routers",
            "unified_api.adapters.inbound.http.identity.routers",
            "unified_api.adapters.inbound.http.guards",
        ]
    )

    # -----------------------------------------------------------------------
    # Database Repositories (Session provided at runtime via kwargs)
    # -----------------------------------------------------------------------
    tenant_repo = providers.Factory(SqlAlchemyTenantRepository)
    tenant_query_service = providers.Factory(SqlAlchemyTenantQueryService)
    app_repo = providers.Factory(SqlAlchemyAppRepository)
    user_repo = providers.Factory(SqlAlchemyUserRepository)
    api_token_repo = providers.Factory(SqlAlchemyApiTokenRepository)
    role_repo = providers.Factory(SqlAlchemyRoleRepository)
    session_factory_provider = db_provider.provided.session_factory
    outbox_repo = providers.Factory(
        SqlAlchemyGlobalOutboxRepository,
        session_factory=session_factory_provider,
        model_cls=UcpOutbox,
        source=UcpOutboxSource.UCP.value,
    )

    # -----------------------------------------------------------------------
    # Unit Of Work (Session provided at runtime via kwargs)
    # -----------------------------------------------------------------------
    uow = providers.Factory(create_ucp_uow)

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
