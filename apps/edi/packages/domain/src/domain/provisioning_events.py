from __future__ import annotations

from pydantic import AnyUrl, BaseModel, ConfigDict, Field


class As2PartnerProvisionedEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="The unique identifier of the AS2 Partner in the Control Plane (CUID)",
    )
    tenantId: str = Field(..., description="The unique identifier of the tenant")
    as2Id: str = Field(..., description="The AS2 routing ID of the partner")
    name: str = Field(..., description="Human readable name of the AS2 Partner")
    url: AnyUrl | None = Field(None, description="The AS2 endpoint URL (if remote)")
    publicCertVaultRef: str | None = Field(
        None, description="Vault reference for the public certificate"
    )
    privateKeyVaultRef: str | None = Field(
        None, description="Vault reference for the private key (if local)"
    )
    isLocal: bool = Field(
        ...,
        description="Whether this partner represents the local tenant or an external trading partner",
    )
    active: bool
