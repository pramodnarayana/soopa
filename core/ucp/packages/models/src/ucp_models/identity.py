from datetime import UTC, datetime

from platform_orm.models.core import UcpBase
from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(UcpBase):
    __tablename__ = "tenants"
    ID_PREFIX = "ten"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idp_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )


class User(UcpBase):
    __tablename__ = "users"
    ID_PREFIX = "usr"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idp_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        {"schema": "ucp"},
    )


class TenantUser(UcpBase):
    __tablename__ = "tenant_users"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), server_default=func.now()
    )

    __table_args__ = ({"schema": "ucp"},)


class ApiToken(UcpBase):
    """
    Platform-managed API keys for machine-to-machine (ERP → Platform) authentication.
    """

    __tablename__ = "api_tokens"
    ID_PREFIX = "tok"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = ({"schema": "ucp"},)


class ApiKey(UcpBase):
    """
    Platform-managed API keys.
    """

    __tablename__ = "api_keys"
    ID_PREFIX = "key"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = ({"schema": "ucp"},)
