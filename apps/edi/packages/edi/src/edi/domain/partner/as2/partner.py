"""AS2 Partner Behavioral Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType, resolve_unset
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiPartnerError

__all__ = ["AS2Partner"]


@dataclass(kw_only=True, eq=False)
class AS2Partner(AggregateRoot):
    """Behavioral Aggregate Root governing AS2 Trading Partner identity & S/MIME certificate rotation."""

    ID_PREFIX = DomainIdPrefix.EDI_AS2_PARTNER.value

    id: str
    as2_id: str
    name: str
    is_local: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None
    prev_public_cert_pem: str | None = None
    prev_public_cert_vault_ref: str | None = None
    prev_private_key_vault_ref: str | None = None
    url: str | None = None
    active: bool = False

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        name: str,
        as2_id: str,
        id: str | None = None,
        is_local: bool = False,
        url: str | None = None,
        public_cert_pem: str | None = None,
        public_cert_vault_ref: str | None = None,
        private_key_vault_ref: str | None = None,
        active: bool = False,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partner, EdiPartnerError]:
        """Create an AS2Partner aggregate with required identifier invariants."""
        if not name or not name.strip() or not as2_id or not as2_id.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="AS2 partner name and as2_id must be non-empty strings.",
                    details={"name": name, "as2_id": as2_id},
                )
            )
        partner_id = id or cls.new_id()
        now = datetime.now(UTC)
        partner = cls(
            id=partner_id,
            tenant_id=tenant_id,
            name=name,
            as2_id=as2_id,
            is_local=is_local,
            url=url,
            public_cert_pem=public_cert_pem,
            public_cert_vault_ref=public_cert_vault_ref,
            private_key_vault_ref=private_key_vault_ref,
            created_at=now,
            updated_at=now,
            active=active,
        )
        partner.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_created,
                resource_id=partner_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(partner)

    def update(
        self,
        *,
        name: str | UnsetType = UNSET,
        as2_id: str | UnsetType = UNSET,
        is_local: bool | UnsetType = UNSET,
        url: str | UnsetType | None = UNSET,
        public_cert_pem: str | UnsetType | None = UNSET,
        public_cert_vault_ref: str | UnsetType | None = UNSET,
        private_key_vault_ref: str | UnsetType | None = UNSET,
        active: bool | UnsetType = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partner, EdiPartnerError]:
        """Atomically validate and update AS2 partner attributes."""
        if not isinstance(name, UnsetType) and not name.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="AS2 partner name cannot be blank.",
                )
            )
        if not isinstance(as2_id, UnsetType) and not as2_id.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="AS2 partner as2_id cannot be blank.",
                )
            )

        next_name = resolve_unset(name, self.name)
        next_as2_id = resolve_unset(as2_id, self.as2_id)
        next_is_local = resolve_unset(is_local, self.is_local)
        next_url = resolve_unset(url, self.url)
        next_public_cert_pem = resolve_unset(public_cert_pem, self.public_cert_pem)
        next_public_cert_vault_ref = resolve_unset(
            public_cert_vault_ref, self.public_cert_vault_ref
        )
        next_private_key_vault_ref = resolve_unset(
            private_key_vault_ref, self.private_key_vault_ref
        )
        next_active = resolve_unset(active, self.active)

        if (
            next_name,
            next_as2_id,
            next_is_local,
            next_url,
            next_public_cert_pem,
            next_public_cert_vault_ref,
            next_private_key_vault_ref,
            next_active,
        ) == (
            self.name,
            self.as2_id,
            self.is_local,
            self.url,
            self.public_cert_pem,
            self.public_cert_vault_ref,
            self.private_key_vault_ref,
            self.active,
        ):
            return Result.ok(self)

        self.name = next_name
        self.as2_id = next_as2_id
        self.is_local = next_is_local
        self.url = next_url
        self.public_cert_pem = next_public_cert_pem
        self.public_cert_vault_ref = next_public_cert_vault_ref
        self.private_key_vault_ref = next_private_key_vault_ref
        self.active = next_active

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def rotate_certificate(
        self,
        *,
        public_cert_pem: str,
        private_key_vault_ref: str | None = None,
        public_cert_vault_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partner, EdiPartnerError]:
        """Rotate active cryptographic certificates into rollover slots and record update event."""
        if not public_cert_pem or not public_cert_pem.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.MISSING_CERTIFICATE,
                    message="public_cert_pem is required to rotate AS2 certificates.",
                )
            )
        if self.is_local and not private_key_vault_ref:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.MISSING_CERTIFICATE,
                    message="private_key_vault_ref is required when rotating certificates for a local AS2 partner.",
                )
            )

        self.prev_public_cert_pem = self.public_cert_pem
        self.prev_public_cert_vault_ref = self.public_cert_vault_ref
        self.prev_private_key_vault_ref = self.private_key_vault_ref
        self.public_cert_pem = public_cert_pem
        self.public_cert_vault_ref = public_cert_vault_ref
        self.private_key_vault_ref = private_key_vault_ref
        self.updated_at = datetime.now(UTC)

        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def activate(self, idempotency_key: str | None = None) -> Result[AS2Partner, EdiPartnerError]:
        """Activate the AS2 partner."""
        if self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_ACTIVE,
                    message=f"AS2 partner '{self.id}' is already active.",
                    details={"partner_id": self.id},
                )
            )
        self.active = True
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def deactivate(self, idempotency_key: str | None = None) -> Result[AS2Partner, EdiPartnerError]:
        """Deactivate the AS2 partner."""
        if not self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_INACTIVE,
                    message=f"AS2 partner '{self.id}' is already inactive.",
                    details={"partner_id": self.id},
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[AS2Partner, EdiPartnerError]:
        """Mark the AS2 partner deleted and record ProvisioningEvent."""
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partner_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)
