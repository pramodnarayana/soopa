from dependency_injector import containers, providers

from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.tenant_query_service import DatabaseTenantQueryService
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.user_repository import UserRepository
from ucp.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp.adapters.outbound.identity.zitadel_organizations_adapter import ZitadelOrganizationsAdapter
from ucp.adapters.outbound.identity.zitadel_projects_adapter import ZitadelProjectsAdapter
from ucp.adapters.outbound.identity.zitadel_users_adapter import ZitadelUsersAdapter
from ucp.application.services.api_token_service import ApiTokenService
from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.application.use_cases.delete_user_use_case import DeleteUserUseCase
from ucp.application.use_cases.invite_user_use_case import InviteUserUseCase
from ucp.application.use_cases.provision_tenant_use_case import ProvisionTenantUseCase
from ucp.application.use_cases.toggle_user_status_use_case import ToggleUserStatusUseCase
from ucp.application.use_cases.update_user_use_case import UpdateUserUseCase


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the UCP bounded context.
    """

    wiring_config = containers.WiringConfiguration(
        packages=[
            "ucp.adapters.inbound.http.routers",
            "ucp.adapters.inbound.http.guards",
        ]
    )

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    zitadel_client = providers.Factory(ZitadelClient)
    project_provider = providers.Factory(ZitadelProjectsAdapter)
    org_provider = providers.Factory(ZitadelOrganizationsAdapter, project_provider=project_provider)
    user_provider = providers.Factory(ZitadelUsersAdapter)

    # -----------------------------------------------------------------------
    # Database Repositories (Session provided at runtime via kwargs)
    # -----------------------------------------------------------------------
    tenant_repo = providers.Factory(TenantRepository)
    tenant_query_service = providers.Factory(DatabaseTenantQueryService)
    app_repo = providers.Factory(PostgresAppRepository)
    user_repo = providers.Factory(UserRepository)
    api_token_repo = providers.Factory(PostgresApiTokenRepository)

    # -----------------------------------------------------------------------
    # Services & Use Cases
    # -----------------------------------------------------------------------
    api_token_service = providers.Factory(
        ApiTokenService,
        token_repo=api_token_repo,
    )

    provision_tenant_use_case = providers.Factory(
        ProvisionTenantUseCase,
        tenant_repo=tenant_repo,
        org_provider=org_provider,
        user_provider=user_provider,
    )

    delete_tenant_use_case = providers.Factory(
        DeleteTenantUseCase,
        tenant_repo=tenant_repo,
        user_repo=user_repo,
        org_provider=org_provider,
    )

    invite_user_use_case = providers.Factory(
        InviteUserUseCase,
        tenant_repo=tenant_repo,
        user_repo=user_repo,
        idp=user_provider,
    )

    update_user_use_case = providers.Factory(
        UpdateUserUseCase,
        tenant_repo=tenant_repo,
        user_repo=user_repo,
        idp=user_provider,
    )

    toggle_user_status_use_case = providers.Factory(
        ToggleUserStatusUseCase,
        tenant_repo=tenant_repo,
        user_repo=user_repo,
        idp=user_provider,
    )

    delete_user_use_case = providers.Factory(
        DeleteUserUseCase,
        tenant_repo=tenant_repo,
        user_repo=user_repo,
        idp=user_provider,
    )
