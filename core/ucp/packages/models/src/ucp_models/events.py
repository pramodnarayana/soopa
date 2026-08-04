from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from platform_orm.models.common import OutboxMixin
from platform_orm.models.core import UcpBase


class ControlPlaneOutbox(UcpBase, OutboxMixin):
    __tablename__ = "outbox"
    ID_PREFIX = "cp_ucp_ob"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (  # type: ignore
        Index(
            "ix_global_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "ucp"},
    )

    @property
    def body(self) -> dict[str, Any]:
        """Alias for payload to satisfy OutboxEvent protocol."""
        return self.payload


class SystemAuditLog(UcpBase):
    __tablename__ = "system_audit_log"
    ID_PREFIX = "log"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    __table_args__ = (  # type: ignore
        Index("ix_system_audit_log_tenant_time", "tenant_id", "created_at"),
        {"schema": "ucp"},
    )
