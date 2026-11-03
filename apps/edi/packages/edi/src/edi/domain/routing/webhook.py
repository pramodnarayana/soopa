"""Read-only Webhook Value Object replicated from UCP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix

__all__ = ["Webhook"]


@dataclass(frozen=True, kw_only=True)
class Webhook:
    """Read-only Value Object representing a UCP-managed webhook egress endpoint."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.EDI_WEBHOOK.value

    id: str
    tenant_id: str
    name: str
    url: str
    active: bool
    created_at: datetime
    updated_at: datetime
    auth_header_vault_ref: str | None = None
