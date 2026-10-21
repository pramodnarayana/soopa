"""Connection aggregate and related value objects for the Integration Platform."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from urllib.parse import urlparse

from seedwork.models import AggregateRoot

from ip.domain.constants import IpDomainIdPrefix
from ip.domain.enums import AuthType, ConnectionStatus
from ip.domain.events import (
    ConnectionActivatedEvent,
    ConnectionCreatedEvent,
    ConnectionDeactivatedEvent,
    ConnectionErrorRecordedEvent,
    ConnectionRelinkedEvent,
)
from ip.domain.exceptions import InvalidConnectionStateException
from ip.domain.types import JsonDict


def compute_connection_fingerprint(tenant_id: str, app_id: str, endpoint: str) -> str:
    """Computes a deterministic SHA-256 fingerprint for a connection.

    Normalizes scheme, host, and port to lowercase, while preserving case-sensitive URL paths.
    """
    cleaned_endpoint = endpoint.strip()
    parsed = urlparse(cleaned_endpoint)
    if parsed.scheme and parsed.netloc:
        normalized_endpoint = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}"
        if parsed.query:
            normalized_endpoint = f"{normalized_endpoint}?{parsed.query}"
    else:
        normalized_endpoint = cleaned_endpoint

    raw = f"{tenant_id.strip().lower()}:{app_id.strip().lower()}:{normalized_endpoint}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(kw_only=True, eq=False)
class Connection(AggregateRoot):
    """Aggregate Root representing an external application connection."""

    ID_PREFIX: ClassVar[str] = IpDomainIdPrefix.CONNECTION

    id: str
    tenant_id: str
    app_id: str
    name: str
    auth_type: AuthType
    public_config: JsonDict = field(default_factory=dict)
    encrypted_credentials: bytes | None = None
    key_encryption_version: int = 1
    connection_fingerprint: str
    status: ConnectionStatus = ConnectionStatus.PENDING_AUTH
    token_expires_at: str | None = None
    last_refreshed_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    deactivated_at: str | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        app_id: str,
        name: str,
        auth_type: AuthType,
        public_config: JsonDict,
        encrypted_credentials: bytes | None,
        endpoint_for_fingerprint: str,
    ) -> Connection:
        """Factory method to create a new Connection aggregate with valid invariants."""
        if not tenant_id.strip():
            raise ValueError("tenant_id cannot be empty")
        if not app_id.strip():
            raise ValueError("app_id cannot be empty")
        if not name.strip():
            raise ValueError("name cannot be empty")

        fingerprint = compute_connection_fingerprint(tenant_id, app_id, endpoint_for_fingerprint)
        conn_id = cls.new_id()

        instance = cls(
            id=conn_id,
            tenant_id=tenant_id,
            app_id=app_id,
            name=name,
            auth_type=auth_type,
            public_config=public_config,
            encrypted_credentials=encrypted_credentials,
            connection_fingerprint=fingerprint,
            status=ConnectionStatus.PENDING_AUTH,
        )

        instance.add_domain_event(
            ConnectionCreatedEvent(
                connection_id=conn_id,
                tenant_id=tenant_id,
                app_id=app_id,
                connection_name=name,
                auth_type=auth_type.value,
            )
        )
        return instance

    def activate(self) -> None:
        """Transitions connection to ACTIVE status once verified."""
        if self.status == ConnectionStatus.DEACTIVATED:
            raise InvalidConnectionStateException(
                f"Cannot activate deactivated connection {self.id}. Use relink() instead."
            )

        self.status = ConnectionStatus.ACTIVE
        self.last_error_code = None
        self.last_error_message = None
        self.updated_at = datetime.now(UTC).isoformat()

        self.add_domain_event(
            ConnectionActivatedEvent(
                connection_id=self.id,
                tenant_id=self.tenant_id,
                app_id=self.app_id,
            )
        )

    def mark_error(self, error_code: str, error_message: str) -> None:
        """Records a connectivity/auth error and marks status as ERROR."""
        if self.status == ConnectionStatus.DEACTIVATED:
            raise InvalidConnectionStateException(
                f"Cannot record error on deactivated connection {self.id}. Relink first."
            )
        self.status = ConnectionStatus.ERROR
        self.last_error_code = error_code
        self.last_error_message = error_message
        self.updated_at = datetime.now(UTC).isoformat()

        self.add_domain_event(
            ConnectionErrorRecordedEvent(
                connection_id=self.id,
                tenant_id=self.tenant_id,
                error_code=error_code,
                error_message=error_message,
            )
        )

    def deactivate(self) -> None:
        """Soft-deactivates the connection without dropping underlying schemas."""
        if self.status == ConnectionStatus.DEACTIVATED:
            return  # Idempotent

        now = datetime.now(UTC).isoformat()
        self.status = ConnectionStatus.DEACTIVATED
        self.deactivated_at = now
        self.updated_at = now

        self.add_domain_event(
            ConnectionDeactivatedEvent(
                connection_id=self.id,
                tenant_id=self.tenant_id,
                app_id=self.app_id,
            )
        )

    def relink(
        self,
        *,
        new_name: str | None = None,
        updated_encrypted_credentials: bytes | None = None,
        updated_public_config: JsonDict | None = None,
    ) -> None:
        """Re-links a previously deactivated connection to resume syncing."""
        if self.status != ConnectionStatus.DEACTIVATED:
            raise InvalidConnectionStateException(
                f"Connection {self.id} is not deactivated (current status: {self.status})."
            )

        now = datetime.now(UTC).isoformat()
        if new_name:
            self.name = new_name
        if updated_encrypted_credentials is not None:
            self.encrypted_credentials = updated_encrypted_credentials
        if updated_public_config is not None:
            self.public_config = updated_public_config
            new_endpoint = (
                updated_public_config.get("endpoint_url")
                or updated_public_config.get("host")
                or updated_public_config.get("base_url")
                or self.app_id
            )
            self.connection_fingerprint = compute_connection_fingerprint(
                self.tenant_id, self.app_id, str(new_endpoint)
            )

        self.status = ConnectionStatus.ACTIVE
        self.deactivated_at = None
        self.last_error_code = None
        self.last_error_message = None
        self.updated_at = now

        self.add_domain_event(
            ConnectionRelinkedEvent(
                connection_id=self.id,
                tenant_id=self.tenant_id,
                app_id=self.app_id,
                relinked_at=now,
            )
        )

    def update_tokens(
        self,
        *,
        encrypted_credentials: bytes,
        token_expires_at: str | None,
        last_refreshed_at: str | None = None,
    ) -> None:
        """Updates OAuth access/refresh tokens in encrypted storage."""
        now = datetime.now(UTC).isoformat()
        self.encrypted_credentials = encrypted_credentials
        self.token_expires_at = token_expires_at
        self.last_refreshed_at = last_refreshed_at or now
        self.updated_at = now
