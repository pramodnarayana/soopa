from datetime import datetime

from ip.adapters.outbound.database.models.base import IpBase
from ip.domain.types import JsonDict
from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ConnectionRecord(IpBase):
    """Database record representation of the ip.connections table."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_fingerprint",
            "status",
            name="uq_tenant_fingerprint_status",
        ),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_config: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_encryption_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    connection_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_AUTH")
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
