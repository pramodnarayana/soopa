from dataclasses import dataclass


@dataclass(frozen=True)
class ProvisionTenantEvent:
    # Keeping for backwards compatibility if needed, though we ignore it.
    tenant_id: str
    name: str


@dataclass(frozen=True)
class ProvisionAllTenantsEvent:
    # This might still be used for global broadcasts.
    pass


@dataclass(frozen=True)
class AS2PartnerCreatedEvent:
    tenant_id: str
    partner_id: str


@dataclass(frozen=True)
class AS2PartnerUpdatedEvent:
    tenant_id: str
    partner_id: str


@dataclass(frozen=True)
class AS2PartnerDeletedEvent:
    tenant_id: str
    partner_id: str
