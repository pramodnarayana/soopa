from typing import Any

from platform_orm.models.common import OutboxMixin
from platform_orm.models.core import UcpBase
from sqlalchemy import Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text


class NotificationTemplate(UcpBase):
    __tablename__ = "notification_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__: Any = (
        UniqueConstraint("tenant_id", "event_type", "channel", name="notification_template_idx"),
        {"schema": "ucp"},
    )


class NotificationOutbox(UcpBase, OutboxMixin):
    __tablename__ = "notification_outbox"
    ID_PREFIX = "notif_ob"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        Index(
            "ix_notif_outbox_pending",
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
