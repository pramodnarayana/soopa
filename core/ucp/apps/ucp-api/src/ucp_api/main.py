import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ucp_api.adapters.inbound.http.guards import tenant_auth_guard
from ucp_api.adapters.inbound.http.routers import tenant_proxy_router, tenants_router, users_router
from ucp_api.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp_api.adapters.outbound.database.tenant_repository import TenantRepository
from ucp_api.adapters.outbound.database.user_repository import UserRepository
from ucp_api.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp_api.adapters.outbound.identity.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from ucp_api.adapters.outbound.identity.zitadel_projects_adapter import ZitadelProjectsAdapter
from ucp_api.adapters.outbound.identity.zitadel_users_adapter import ZitadelUsersAdapter
from ucp_api.adapters.outbound.messaging.postgres_notify_outbox_publisher import (
    PostgresNotifyOutboxPublisher,
)
from ucp_api.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp_api.application.use_cases.delete_user_use_case import DeleteUserUseCase
from ucp_api.application.use_cases.invite_user_use_case import InviteUserUseCase
from ucp_api.application.use_cases.provision_tenant_use_case import ProvisionTenantUseCase
from ucp_api.application.use_cases.toggle_user_status_use_case import ToggleUserStatusUseCase
from ucp_api.application.use_cases.update_user_use_case import UpdateUserUseCase
from ucp_api.application.workers.outbox_sweeper import ControlPlaneOutboxSweeper
from ucp_api.core.container import get_db_session
from ucp_api.core.exceptions import IdentityProviderError

logger = logging.getLogger(__name__)

# HTTPX client for Zitadel admin calls \u2014 closed on shutdown
_zitadel_httpx_client = httpx.AsyncClient()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Setup session factory for background task
    database_url = os.environ.get("DATABASE_URL")
    if database_url and database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, pool_pre_ping=True) if database_url else None

    sweeper = None
    if engine:
        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        sweeper = ControlPlaneOutboxSweeper(
            repository=PostgresOutboxRepository(session_factory),
            publisher=PostgresNotifyOutboxPublisher(session_factory),
            poll_interval_seconds=int(os.environ.get("OUTBOX_POLL_INTERVAL_SECONDS", "2")),
        )
        sweeper.start()
    else:
        logger.warning("DATABASE_URL not set, ControlPlaneOutboxSweeper will not start.")

    yield

    if sweeper:
        await sweeper.stop()
    if engine:
        await engine.dispose()

    await _zitadel_httpx_client.aclose()


app = FastAPI(title="UCP API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IdentityProviderError)
async def identity_provider_exception_handler(
    request: Request, exc: IdentityProviderError
) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal identity provider error occurred."},
    )


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------
def get_zitadel_client() -> ZitadelClient:
    return ZitadelClient()


def get_tenant_repo(session: AsyncSession = Depends(get_db_session)) -> TenantRepository:
    return TenantRepository(session)


def get_user_repo(session: AsyncSession = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)


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


# ---------------------------------------------------------------------------
# Dependency injection wiring \u2014 connect real adapters to router placeholders
# ---------------------------------------------------------------------------
app.dependency_overrides[tenants_router.get_tenant_repo] = get_tenant_repo
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

app.dependency_overrides[tenant_proxy_router.get_tenant_repo] = get_tenant_repo

# The tenant_auth_guard needs a TenantRepository to resolve IdP tenant IDs.
# We override its placeholder here so it participates in the request-scoped
# DB session lifecycle, exactly like the routers above.
app.dependency_overrides[tenant_auth_guard.get_tenant_repo_for_guard] = get_tenant_repo

app.include_router(tenants_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")
app.include_router(tenant_proxy_router.router, prefix="/api/v1")
