"""SFTP Partner Behavioral Domain Models."""

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

__all__ = ["SFTPPartner"]


def _normalize_optional_secret(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


@dataclass(kw_only=True, eq=False)
class SFTPPartner(AggregateRoot):
    """Behavioral Aggregate Root governing SFTP Trading Partner connection & credential invariants."""

    ID_PREFIX = DomainIdPrefix.EDI_SFTP_PARTNER.value

    id: str
    tenant_id: str
    name: str
    host: str
    port: int
    username: str
    active: bool
    created_at: datetime
    updated_at: datetime
    host_key: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    password_encrypted: str | None = None
    credentials_vault_ref: str | None = None
    deleted_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        name: str,
        host: str,
        username: str,
        port: int = 22,
        id: str | None = None,
        host_key: str | None = None,
        inbound_remote_path: str | None = None,
        outbound_remote_path: str | None = None,
        password_encrypted: str | None = None,
        credentials_vault_ref: str | None = None,
        active: bool = False,
        idempotency_key: str | None = None,
    ) -> Result[SFTPPartner, EdiPartnerError]:
        """Create an SFTPPartner aggregate enforcing endpoint, port, and XOR credential invariants."""
        if (
            not name
            or not name.strip()
            or not host
            or not host.strip()
            or not username
            or not username.strip()
        ):
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner name, host, and username must be non-empty.",
                )
            )
        if port < 1 or port > 65535:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP port must be between 1 and 65535.",
                    details={"port": port},
                )
            )

        normalized_password = _normalize_optional_secret(password_encrypted)
        normalized_vault_ref = _normalize_optional_secret(credentials_vault_ref)
        if not normalized_password and not normalized_vault_ref:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner must have either a password or a credentials_vault_ref.",
                )
            )
        if normalized_password and normalized_vault_ref:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner cannot have both a password and a credentials_vault_ref.",
                )
            )

        partner_id = id or cls.new_id()
        now = datetime.now(UTC)
        partner = cls(
            id=partner_id,
            tenant_id=tenant_id,
            name=name,
            host=host,
            port=port,
            username=username,
            host_key=host_key,
            inbound_remote_path=inbound_remote_path,
            outbound_remote_path=outbound_remote_path,
            password_encrypted=normalized_password,
            credentials_vault_ref=normalized_vault_ref,
            active=active,
            created_at=now,
            updated_at=now,
        )
        partner.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_created,
                resource_id=partner_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(partner)

    def _validate_updated_credentials(
        self,
        *,
        password_encrypted: str | UnsetType | None,
        credentials_vault_ref: str | UnsetType | None,
    ) -> Result[tuple[str | None, str | None], EdiPartnerError]:
        next_password = _normalize_optional_secret(
            resolve_unset(password_encrypted, self.password_encrypted)
        )
        next_vault_ref = _normalize_optional_secret(
            resolve_unset(credentials_vault_ref, self.credentials_vault_ref)
        )
        if not next_password and not next_vault_ref:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner must have either a password or a credentials_vault_ref",
                )
            )
        if next_password and next_vault_ref:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner cannot have both a password and a credentials_vault_ref",
                )
            )
        return Result.ok((next_password, next_vault_ref))

    def update(
        self,
        *,
        name: str | UnsetType = UNSET,
        host: str | UnsetType = UNSET,
        username: str | UnsetType = UNSET,
        port: int | UnsetType = UNSET,
        host_key: str | UnsetType | None = UNSET,
        inbound_remote_path: str | UnsetType | None = UNSET,
        outbound_remote_path: str | UnsetType | None = UNSET,
        password_encrypted: str | UnsetType | None = UNSET,
        credentials_vault_ref: str | UnsetType | None = UNSET,
        active: bool | UnsetType = UNSET,
        idempotency_key: str | None = None,
    ) -> Result[SFTPPartner, EdiPartnerError]:
        """Atomically validate and update SFTP partner attributes including credential exclusivity."""
        if not isinstance(name, UnsetType) and not name.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner name cannot be blank.",
                )
            )
        if not isinstance(host, UnsetType) and not host.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner host cannot be blank.",
                )
            )
        if not isinstance(username, UnsetType) and not username.strip():
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP partner username cannot be blank.",
                )
            )
        if not isinstance(port, UnsetType) and (port < 1 or port > 65535):
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.VALIDATION_FAILED,
                    message="SFTP port must be between 1 and 65535.",
                    details={"port": port},
                )
            )

        cred_validation = self._validate_updated_credentials(
            password_encrypted=password_encrypted,
            credentials_vault_ref=credentials_vault_ref,
        )
        if cred_validation.is_err:
            return Result.fail(cred_validation.unwrap_err())
        next_password, next_vault_ref = cred_validation.unwrap()

        next_name = resolve_unset(name, self.name)
        next_host = resolve_unset(host, self.host)
        next_username = resolve_unset(username, self.username)
        next_port = resolve_unset(port, self.port)
        next_host_key = resolve_unset(host_key, self.host_key)
        next_inbound = resolve_unset(inbound_remote_path, self.inbound_remote_path)
        next_outbound = resolve_unset(outbound_remote_path, self.outbound_remote_path)
        next_active = resolve_unset(active, self.active)

        if (
            next_name,
            next_host,
            next_username,
            next_port,
            next_host_key,
            next_inbound,
            next_outbound,
            next_password,
            next_vault_ref,
            next_active,
        ) == (
            self.name,
            self.host,
            self.username,
            self.port,
            self.host_key,
            self.inbound_remote_path,
            self.outbound_remote_path,
            self.password_encrypted,
            self.credentials_vault_ref,
            self.active,
        ):
            return Result.ok(self)

        self.name = next_name
        self.host = next_host
        self.username = next_username
        self.port = next_port
        self.host_key = next_host_key
        self.inbound_remote_path = next_inbound
        self.outbound_remote_path = next_outbound
        self.password_encrypted = next_password
        self.credentials_vault_ref = next_vault_ref
        self.active = next_active

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def activate(self, idempotency_key: str | None = None) -> Result[SFTPPartner, EdiPartnerError]:
        """Activate the SFTP partner."""
        if self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_ACTIVE,
                    message=f"SFTP partner '{self.id}' is already active.",
                )
            )
        self.active = True
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def deactivate(
        self, idempotency_key: str | None = None
    ) -> Result[SFTPPartner, EdiPartnerError]:
        """Deactivate the SFTP partner."""
        if not self.active:
            return Result.fail(
                EdiPartnerError(
                    code=EdiErrorCode.PARTNER_ALREADY_INACTIVE,
                    message=f"SFTP partner '{self.id}' is already inactive.",
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_sftp_partner_updated,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)

    def mark_deleted(
        self, idempotency_key: str | None = None
    ) -> Result[SFTPPartner, EdiPartnerError]:
        """Mark the SFTP partner deleted and record ProvisioningEvent."""
        now = datetime.now(UTC)
        self.active = False
        self.deleted_at = now
        self.updated_at = now
        self.add_domain_event(
            ProvisioningEvent(
                tenant_id=self.tenant_id,
                event_type=EdiEventType.edi_sftp_partner_deleted,
                resource_id=self.id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY),
            )
        )
        return Result.ok(self)
