from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

from identity.domain.constants import IdentityIdPrefix
from identity.domain.exceptions import IdentityError, IdentityErrorCode


def _normalize_utc(value: datetime) -> datetime:
    """Normalize naive timestamps as UTC while preserving timezone-aware instants."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(kw_only=True, eq=False)
class ApiToken(AggregateRoot):
    """Aggregate root representing an M2M API token owned by a tenant."""

    ID_PREFIX: ClassVar[str] = IdentityIdPrefix.TOKEN.value

    id: str
    tenant_id: str
    name: str
    client_id: str
    secret_hash: str
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        name: str,
        client_id: str,
        secret_hash: str,
        expires_at: datetime | None = None,
        token_id: str | None = None,
    ) -> Result[ApiToken, IdentityError]:
        cleaned_name = name.strip()
        if not cleaned_name:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN_NAME,
                    message="API token name cannot be empty.",
                )
            )
        now = datetime.now(UTC)
        return Result.ok(
            cls(
                id=token_id or generate_id(cls.ID_PREFIX),
                tenant_id=tenant_id,
                name=cleaned_name,
                client_id=client_id,
                secret_hash=secret_hash,
                last_used_at=None,
                expires_at=expires_at,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )

    def rename(self, new_name: str) -> Result[ApiToken, IdentityError]:
        cleaned_name = new_name.strip()
        if not cleaned_name:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN_NAME,
                    message="API token name cannot be empty.",
                )
            )
        if self.name != cleaned_name:
            self.name = cleaned_name
            self.updated_at = datetime.now(UTC)
        return Result.ok(self)

    def revoke(self) -> Result[ApiToken, IdentityError]:
        if not self.active:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.TOKEN_ALREADY_REVOKED,
                    message=f"API token '{self.id}' is already revoked.",
                )
            )
        self.active = False
        self.updated_at = datetime.now(UTC)
        return Result.ok(self)

    def activate(self) -> Result[ApiToken, IdentityError]:
        if not self.active:
            self.active = True
            self.updated_at = datetime.now(UTC)
        return Result.ok(self)

    def is_expired(self, *, at: datetime | None = None) -> bool:
        """Return True when the token has an expiration timestamp at or before `at`."""
        if self.expires_at is None:
            return False
        reference_time = _normalize_utc(at) if at is not None else datetime.now(UTC)
        return reference_time >= _normalize_utc(self.expires_at)

    def record_usage(
        self,
        *,
        used_at: datetime | None = None,
    ) -> Result[ApiToken, IdentityError]:
        if not self.active:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.TOKEN_INACTIVE,
                    message=f"API token '{self.id}' is inactive.",
                )
            )
        effective_used_at = used_at or datetime.now(UTC)
        if self.is_expired(at=effective_used_at):
            assert self.expires_at is not None
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.TOKEN_EXPIRED,
                    message=f"API token '{self.id}' expired at {self.expires_at.isoformat()}.",
                )
            )
        self.last_used_at = effective_used_at
        self.updated_at = effective_used_at
        return Result.ok(self)
