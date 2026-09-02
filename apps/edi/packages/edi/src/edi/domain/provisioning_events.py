from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class As2PartnerProvisionedEvent:
    id: str
    tenantId: str
    as2Id: str
    name: str
    url: str | None = None
    publicCertVaultRef: str | None = None
    privateKeyVaultRef: str | None = None
    isLocal: bool = False
    active: bool = False
