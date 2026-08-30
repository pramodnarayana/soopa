# 1. Setup minimal dependencies to isolate the authentication middleware mapping logic
from collections.abc import Iterator
from typing import Annotated, Any

import pytest

# We rely on .env for default test settings. Do not pollute os.environ statically.
from dependency_injector import providers
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from identity.domain.identity_context import IdentityContext
from ucp.bootstrap.container import Container

from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member


class MockTenant:
    id = "ten_683c22ac40ee6e7b70e7a604"


class MockTenantRepo:
    def __init__(self, session: Any = None) -> None:
        pass

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> MockTenant | None:
        if idp_tenant_id == "385223051081416707":
            return MockTenant()
        return None


router = APIRouter()


@router.get("/api/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str, identity: Annotated[IdentityContext, Depends(require_tenant_member)]
) -> dict[str, str]:
    return {"status": "success", "tenant_id": tenant_id}


@pytest.fixture
def container() -> Iterator[Container]:
    """Configure and provide a test container with proper cleanup."""
    test_container = Container()
    test_container.tenant_repo.override(providers.Factory(MockTenantRepo))
    test_container.wire(modules=["unified_api.adapters.inbound.http.guards.tenant_auth_guard"])
    yield test_container
    test_container.unwire()
    test_container.tenant_repo.reset_override()


@pytest.fixture
def app(container: Container) -> FastAPI:
    """Create test app with configured container."""
    test_app = FastAPI(title="Unified API Auth Mapping Test")
    test_app.include_router(router)

    @test_app.middleware("http")
    async def authentication_middleware(request: Request, call_next: Any) -> Any:
        import dataclasses

        repo = MockTenantRepo()

        mapped_tenants = set()
        new_tenant_id = raw_identity.tenant_id

        for tid in raw_identity.authorized_tenants:
            if not tid.startswith("ten_") and tid != "ten_000000000000000000000000":
                resolved_t = await repo.find_by_idp_tenant_id(tid)
                if resolved_t:
                    mapped_tenants.add(resolved_t.id)
                    mapped_tenants.add(tid)  # retain IdP ID
                    if not new_tenant_id:
                        new_tenant_id = resolved_t.id
                else:
                    raise HTTPException(status_code=403, detail="Not found")
            else:
                mapped_tenants.add(tid)

        identity = dataclasses.replace(
            raw_identity, authorized_tenants=mapped_tenants, tenant_id=new_tenant_id
        )
        request.state.identity = identity
        return await call_next(request)

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


# 2. Simulate the Middleware mapping logic (which sits at the Unified API perimeter)
# In standard testing, we would use the real DB. Here we test the pure mapping logic.
raw_identity = IdentityContext(
    subject="385223078428278787",
    tenant_id=None,
    authorized_tenants={"385223051081416707"},
    claims={},
)


def test_tenant_auth_accepts_idp_id(client: TestClient) -> None:
    """
    Ensures that when a user requests the IdP Tenant ID in the URL,
    the perimeter mapping logic correctly authorizes it without a 403.
    """
    idp_id = "385223051081416707"
    response = client.get(f"/api/v1/tenants/{idp_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "tenant_id": idp_id}


def test_tenant_auth_accepts_canonical_id(client: TestClient) -> None:
    """
    Ensures that when a user requests the Canonical UCP Tenant ID in the URL,
    the perimeter mapping logic correctly authorizes it without a 403.
    """
    can_id = "ten_683c22ac40ee6e7b70e7a604"
    response = client.get(f"/api/v1/tenants/{can_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "tenant_id": can_id}
