"""AS2 Partnership Behavioral Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, JsonDict, UnsetType, resolve_defined, resolve_unset
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import EdiErrorCode, EdiPartnerError
from edi.domain.partner.as2.enums import (
    EncryptionAlgorithm,
    MDNType,
    SignatureAlgorithm,
)

__all__ = ["AS2Partnership"]


@dataclass(kw_only=True, eq=False)
class AS2Partnership(AggregateRoot):
    """Behavioral Aggregate Root governing bilateral AS2 Partnership cryptographic & MDN agreements."""

    ID_PREFIX = DomainIdPrefix.EDI_AS2_PARTNERSHIP.value

    id: str
    name: str
    local_partner_id: str
    remote_partner_id: str
    mdn_type: str
    encryption_algorithm: str
    signature_algorithm: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    credentials_vault_ref: str | None = None
    mdn_url: str | None = None
    advanced_flags: JsonDict | None = None
    active: bool = False

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        name: str,
        local_partner_id: str,
        remote_partner_id: str,
        id: str | None = None,
        mdn_type: str = MDNType.SYNC,
        encryption_algorithm: str = EncryptionAlgorithm.AES256,
        signature_algorithm: str = SignatureAlgorithm.SHA256,
        credentials_vault_ref: str | None = None,
        mdn_url: str | None = None,
        advanced_flags: JsonDict | None = None,
        active: bool = True,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partnership, EdiPartnerError]:
        """Create an AS2Partnership aggregate enforcing distinct local/remote partner invariants."""
        if (
            not name
            or not name.strip()
            or not local_partner_id
            or not local_partner_id.strip()
            or not remote_partner_id
            or not remote_partner_id.strip()
        ):
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="Partnership name, local_partner_id, and remote_partner_id must be non-empty.",
                )
            )
        if local_partner_id == remote_partner_id:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="local_partner_id and remote_partner_id must reference distinct AS2 partners.",
                    details={"partner_id": local_partner_id},
                )
            )

        partnership_id = id or cls.new_id()
        now = datetime.now(UTC)
        partnership = cls(
            id=partnership_id,
            name=name,
            local_partner_id=local_partner_id,
            remote_partner_id=remote_partner_id,
            mdn_type=mdn_type,
            encryption_algorithm=encryption_algorithm,
            signature_algorithm=signature_algorithm,
            created_at=now,
            updated_at=now,
            tenant_id=tenant_id,
            active=active,
            mdn_url=mdn_url,
            credentials_vault_ref=credentials_vault_ref,
            advanced_flags=advanced_flags,
        )
        partnership.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_created,
                resource_id=partnership_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(partnership)

    def update(
        self,
        *,
        name: str | UnsetType | None = UNSET,
        credentials_vault_ref: str | UnsetType | None = UNSET,
        mdn_type: str | UnsetType | None = UNSET,
        mdn_url: str | UnsetType | None = UNSET,
        encryption_algorithm: str | UnsetType | None = UNSET,
        signature_algorithm: str | UnsetType | None = UNSET,
        advanced_flags: JsonDict | UnsetType | None = UNSET,
        active: bool | UnsetType | None = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[AS2Partnership, EdiPartnerError]:
        """Explicitly update AS2 partnership attributes without dynamic reflection."""
        if not isinstance(name, UnsetType) and (name is None or not name.strip()):
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="AS2 partnership name cannot be empty.",
                )
            )
        if not isinstance(mdn_type, UnsetType) and mdn_type is None:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="mdn_type cannot be None.",
                )
            )
        if not isinstance(encryption_algorithm, UnsetType) and encryption_algorithm is None:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="encryption_algorithm cannot be None.",
                )
            )
        if not isinstance(signature_algorithm, UnsetType) and signature_algorithm is None:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="signature_algorithm cannot be None.",
                )
            )

        next_name = resolve_defined(name, self.name)
        next_credentials_vault_ref = resolve_unset(
            credentials_vault_ref, self.credentials_vault_ref
        )
        next_mdn_type = resolve_defined(mdn_type, self.mdn_type)
        next_mdn_url = resolve_unset(mdn_url, self.mdn_url)
        next_encryption_algorithm = resolve_defined(encryption_algorithm, self.encryption_algorithm)
        next_signature_algorithm = resolve_defined(signature_algorithm, self.signature_algorithm)
        next_advanced_flags = resolve_unset(advanced_flags, self.advanced_flags)
        next_active = resolve_defined(active, self.active)

        if (
            next_name,
            next_credentials_vault_ref,
            next_mdn_type,
            next_mdn_url,
            next_encryption_algorithm,
            next_signature_algorithm,
            next_advanced_flags,
            next_active,
        ) == (
            self.name,
            self.credentials_vault_ref,
            self.mdn_type,
            self.mdn_url,
            self.encryption_algorithm,
            self.signature_algorithm,
            self.advanced_flags,
            self.active,
        ):
            return Result.ok(self)

        self.name = next_name
        self.credentials_vault_ref = next_credentials_vault_ref
        self.mdn_type = next_mdn_type
        self.mdn_url = next_mdn_url
        self.encryption_algorithm = next_encryption_algorithm
        self.signature_algorithm = next_signature_algorithm
        self.advanced_flags = next_advanced_flags
        self.active = next_active

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def activate(
        self, idempotency_key: str | None = None
    ) -> Result[AS2Partnership, EdiPartnerError]:
        """Activate the AS2 partnership."""
        if self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_ACTIVE,
                    message=f"AS2 partnership '{self.id}' is already active.",
                )
            )
        self.active = True
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def deactivate(
        self, idempotency_key: str | None = None
    ) -> Result[AS2Partnership, EdiPartnerError]:
        """Deactivate the AS2 partnership."""
        if not self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_INACTIVE,
                    message=f"AS2 partnership '{self.id}' is already inactive.",
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[AS2Partnership, EdiPartnerError]:
        """Mark the AS2 partnership deleted and record ProvisioningEvent."""
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id or "",
                event_type=EdiEventType.edi_as2_partnership_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)
