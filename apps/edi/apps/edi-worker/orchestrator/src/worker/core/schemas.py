from pydantic import BaseModel


class ProvisionTenantEvent(BaseModel):
    # Keeping for backwards compatibility if needed, though we ignore it.
    tenant_id: str
    name: str | None = None


class ProvisionAllTenantsEvent(BaseModel):
    # This might still be used for global broadcasts.
    pass


class AS2PartnerCreatedEvent(BaseModel):
    tenant_id: str
    partner_id: str


class AS2PartnerUpdatedEvent(BaseModel):
    tenant_id: str
    partner_id: str


class AS2PartnerDeletedEvent(BaseModel):
    tenant_id: str
    partner_id: str
