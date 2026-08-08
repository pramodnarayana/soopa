from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.inbound.http.routers import (
    apps_router,
    tenants_router,
    tokens_router,
    users_router,
)
from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.tenant_query_service import DatabaseTenantQueryService
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.user_repository import UserRepository
from ucp.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp.adapters.outbound.identity.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from ucp.adapters.outbound.identity.zitadel_projects_adapter import ZitadelProjectsAdapter
from ucp.adapters.outbound.identity.zitadel_users_adapter import ZitadelUsersAdapter
from ucp.application.services.api_token_service import ApiTokenService
from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.application.use_cases.delete_user_use_case import DeleteUserUseCase
from ucp.application.use_cases.invite_user_use_case import InviteUserUseCase
from ucp.application.use_cases.provision_tenant_use_case import ProvisionTenantUseCase
from ucp.application.use_cases.toggle_user_status_use_case import ToggleUserStatusUseCase
from ucp.application.use_cases.update_user_use_case import UpdateUserUseCase
from ucp.core.container import get_db_session


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------
def get_zitadel_client() -> ZitadelClient:
    return ZitadelClient()


def get_tenant_repo(session: AsyncSession = Depends(get_db_session)) -> TenantRepository:
    return TenantRepository(session)


def get_tenant_query_service(
    session: AsyncSession = Depends(get_db_session),
) -> DatabaseTenantQueryService:
    return DatabaseTenantQueryService(session)


def get_app_repo(session: AsyncSession = Depends(get_db_session)) -> PostgresAppRepository:
    return PostgresAppRepository(session)


def get_user_repo(session: AsyncSession = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)


def get_api_token_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresApiTokenRepository:
    return PostgresApiTokenRepository(session)


def get_api_token_service(
    token_repo: PostgresApiTokenRepository = Depends(get_api_token_repo),
) -> ApiTokenService:
    return ApiTokenService(token_repo)


def get_project_provider() -> ZitadelProjectsAdapter:
    return ZitadelProjectsAdapter()


def get_org_provider(
    project_provider: ZitadelProjectsAdapter = Depends(get_project_provider),
) -> ZitadelOrganizationsAdapter:
    return ZitadelOrganizationsAdapter(project_provider)


def get_user_provider() -> ZitadelUsersAdapter:
    return ZitadelUsersAdapter()


def get_provision_tenant_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    org_provider: ZitadelOrganizationsAdapter = Depends(get_org_provider),
    user_provider: ZitadelUsersAdapter = Depends(get_user_provider),
) -> ProvisionTenantUseCase:
    return ProvisionTenantUseCase(tenant_repo, org_provider, user_provider)


def get_delete_tenant_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    org_provider: ZitadelOrganizationsAdapter = Depends(get_org_provider),
) -> DeleteTenantUseCase:
    return DeleteTenantUseCase(tenant_repo, user_repo, org_provider)


def get_invite_user_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    idp: ZitadelUsersAdapter = Depends(get_user_provider),
) -> InviteUserUseCase:
    return InviteUserUseCase(tenant_repo, user_repo, idp)


def get_update_user_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    idp: ZitadelUsersAdapter = Depends(get_user_provider),
) -> UpdateUserUseCase:
    return UpdateUserUseCase(tenant_repo, user_repo, idp)


def get_toggle_user_status_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    idp: ZitadelUsersAdapter = Depends(get_user_provider),
) -> ToggleUserStatusUseCase:
    return ToggleUserStatusUseCase(tenant_repo, user_repo, idp)


def get_delete_user_use_case(
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    idp: ZitadelUsersAdapter = Depends(get_user_provider),
) -> DeleteUserUseCase:
    return DeleteUserUseCase(tenant_repo, user_repo, idp)


def setup_dependency_injection(app: FastAPI) -> None:
    """
    Connects real adapters to router placeholders via FastAPI dependency overrides.
    """
    app.dependency_overrides[tenants_router.get_tenant_repo] = get_tenant_repo
    app.dependency_overrides[tenants_router.get_tenant_query_service] = get_tenant_query_service
    app.dependency_overrides[tenants_router.get_project_provider] = get_project_provider
    app.dependency_overrides[tenants_router.get_provision_tenant_use_case] = (
        get_provision_tenant_use_case
    )
    app.dependency_overrides[tenants_router.get_delete_tenant_use_case] = get_delete_tenant_use_case

    app.dependency_overrides[users_router.get_tenant_repo] = get_tenant_repo
    app.dependency_overrides[users_router.get_user_repo] = get_user_repo
    app.dependency_overrides[users_router.get_invite_user_use_case] = get_invite_user_use_case
    app.dependency_overrides[users_router.get_update_user_use_case] = get_update_user_use_case
    app.dependency_overrides[users_router.get_toggle_user_status_use_case] = (
        get_toggle_user_status_use_case
    )
    app.dependency_overrides[users_router.get_delete_user_use_case] = get_delete_user_use_case

    app.dependency_overrides[apps_router.get_app_repo] = get_app_repo

    app.dependency_overrides[tokens_router.get_api_token_service] = get_api_token_service

    # The tenant_auth_guard needs a TenantRepository to resolve IdP tenant IDs.
    # We override its placeholder here so it participates in the request-scoped
    # DB session lifecycle, exactly like the routers above.
    from ucp.adapters.inbound.http.guards import tenant_auth_guard

    app.dependency_overrides[tenant_auth_guard.get_tenant_repo_for_guard] = get_tenant_repo
