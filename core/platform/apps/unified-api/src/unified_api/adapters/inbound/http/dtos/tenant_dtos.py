"""HTTP-layer request/response DTOs for the Tenants resource.

These Pydantic models are the API contract — they live at the HTTP boundary and
must NOT be imported from the Application or Domain layers.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from ucp.ports.outbound.tenant_query_service import TenantReadModel


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

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    idp_tenant_id: str | None = Field(serialization_alias="zitadelOrgId")
    status: str
    subscriptions: list[str]
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")

    @classmethod
    def from_read_model(cls, rm: TenantReadModel) -> "TenantResponse":
        return cls(
            id=rm.id,
            name=rm.name,
            slug=rm.slug,
            idp_tenant_id=rm.idp_tenant_id,
            status=rm.status,
            subscriptions=rm.subscriptions,
            created_at=rm.created_at,
            updated_at=rm.updated_at,
        )
