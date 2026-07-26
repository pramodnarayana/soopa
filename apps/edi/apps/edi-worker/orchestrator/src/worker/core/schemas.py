from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

DISCRIMINATOR_FIELD = "target"


class ProvisionTarget(StrEnum):
    PROVISION_TENANT = "provision_tenant"
    PROVISION_ALL_TENANTS = "provision_all_tenants"


class BaseProvisionEvent(BaseModel):
    target: ProvisionTarget


class ProvisionTenantEvent(BaseProvisionEvent):
    target: Literal[ProvisionTarget.PROVISION_TENANT] = ProvisionTarget.PROVISION_TENANT
    tenant_id: str


class ProvisionAllTenantsEvent(BaseProvisionEvent):
    target: Literal[ProvisionTarget.PROVISION_ALL_TENANTS] = ProvisionTarget.PROVISION_ALL_TENANTS


ProvisionEventPayload = Annotated[
    ProvisionTenantEvent | ProvisionAllTenantsEvent,
    Field(discriminator=DISCRIMINATOR_FIELD),
]
