"""HTTP-layer request/response DTOs for the Tenants resource.

These Pydantic models are the API contract — they live at the HTTP boundary and
must NOT be imported from the Application or Domain layers.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ProvisionTenantRequest(BaseModel):
    """Request body for POST /tenants/."""

    name: str = Field(..., min_length=1, description="Human-readable name for the new tenant.")


class UpdateTenantNameRequest(BaseModel):
    """Request body for PATCH /tenants/{id}/name."""

    name: str = Field(..., min_length=1)


class UpdateTenantStatusRequest(BaseModel):
    """Request body for PATCH /tenants/{id}/status."""

    status: str = Field(..., pattern="^(active|inactive)$")


class TenantResponse(BaseModel):
    """Response shape for all Tenant endpoints."""

    id: str
    name: str
    idp_tenant_id: Optional[str]
    status: str
    subscriptions: List[str]

    @classmethod
    def from_domain(cls, tenant: object) -> "TenantResponse":
        return cls(
            id=tenant.id,  # type: ignore[attr-defined]
            name=tenant.name,  # type: ignore[attr-defined]
            idp_tenant_id=tenant.idp_tenant_id,  # type: ignore[attr-defined]
            status=tenant.status,  # type: ignore[attr-defined]
            subscriptions=tenant.subscriptions,  # type: ignore[attr-defined]
        )
