# 1. Setup minimal dependencies to isolate the authentication middleware mapping logic
import os
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

os.environ["ZITADEL_API_TOKEN"] = "test-token"  # noqa: S105
os.environ["ZITADEL_UCP_PROJECT_ID"] = "test-project"
os.environ["ZITADEL_PLATFORM_ORG_ID"] = "test-org"


from dependency_injector import providers
from identity.domain.identity_context import IdentityContext
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.bootstrap.container import Container

app = FastAPI(title="Unified API Auth Mapping Test")


class MockTenant:
    id = "ten_683c22ac40ee6e7b70e7a604"


class MockTenantRepo:
    def __init__(self, session=None):
        pass

    async def find_by_idp_tenant_id(self, idp_tenant_id: str):
        if idp_tenant_id == "385223051081416707":
            return MockTenant()
        return None


router = APIRouter()


@router.get("/api/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str, identity: Annotated[IdentityContext, Depends(require_tenant_member)]
):
    return {"status": "success", "tenant_id": tenant_id}


app.include_router(router)

container = Container()
container.tenant_repo.override(providers.Factory(MockTenantRepo))
container.wire(modules=["ucp.adapters.inbound.http.guards.tenant_auth_guard"])

client = TestClient(app)

# 2. Simulate the Middleware mapping logic (which sits at the Unified API perimeter)
# In standard testing, we would use the real DB. Here we test the pure mapping logic.
raw_identity = IdentityContext(
    subject="385223078428278787",
    tenant_id=None,
    authorized_tenants={"385223051081416707"},
    claims={},
)


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    identity = raw_identity.model_copy()
    repo = MockTenantRepo()

    mapped_tenants = set()
    for tid in identity.authorized_tenants:
        if not tid.startswith("ten_") and tid != "ten_000000000000000000000000":
            resolved_t = await repo.find_by_idp_tenant_id(tid)
            if resolved_t:
                mapped_tenants.add(resolved_t.id)
                mapped_tenants.add(tid)  # retain IdP ID
                if not identity.tenant_id:
                    identity.tenant_id = resolved_t.id
            else:
                raise HTTPException(status_code=403, detail="Not found")
        else:
            mapped_tenants.add(tid)

    identity.authorized_tenants = mapped_tenants
    request.state.identity = identity
    return await call_next(request)


def test_tenant_auth_accepts_idp_id():
    """
    Ensures that when a user requests the IdP Tenant ID in the URL,
    the perimeter mapping logic correctly authorizes it without a 403.
    """
    idp_id = "385223051081416707"
    response = client.get(f"/api/v1/tenants/{idp_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "tenant_id": idp_id}


def test_tenant_auth_accepts_canonical_id():
    """
    Ensures that when a user requests the Canonical UCP Tenant ID in the URL,
    the perimeter mapping logic correctly authorizes it without a 403.
    """
    can_id = "ten_683c22ac40ee6e7b70e7a604"
    response = client.get(f"/api/v1/tenants/{can_id}")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "tenant_id": can_id}
