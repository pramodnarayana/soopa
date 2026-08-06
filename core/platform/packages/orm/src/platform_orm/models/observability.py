from datetime import UTC, datetime

from database.models.replicated_mixins import WebhookMixin
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_orm.models.common import TimestampMixin
from platform_orm.models.core import ObservabilityBase


class SystemAuditLog(ObservabilityBase):
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

    __table_args__ = (
        Index("ix_system_audit_log_tenant_time", "tenant_id", "created_at"),
        {"schema": "observability"},
    )


class Webhook(ObservabilityBase, WebhookMixin, TimestampMixin):
    __tablename__ = "webhooks"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
