from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from platform_orm.models.common import OutboxMixin, TimestampMixin
from platform_orm.models.core import NotificationBase


class NotificationTemplate(NotificationBase, TimestampMixin):
    __tablename__ = "notification_templates"
    ID_PREFIX = "notif_tmpl"

    id: Mapped[str] = mapped_column(String(128), primary_key=True, autoincrement=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__: Any = (
        UniqueConstraint("tenant_id", "event_type", "channel", name="notification_template_idx"),
        {"schema": "notifications"},
    )


class NotificationOutbox(NotificationBase, OutboxMixin):
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
        {"schema": "notifications"},
    )

    @property
    def body(self) -> dict[str, Any]:
        """Alias for payload to satisfy OutboxEvent protocol."""
        return self.payload


class NotificationRouteConfiguration(NotificationBase, TimestampMixin):
    __tablename__ = "notification_route_configurations"
    ID_PREFIX = "notif_rte"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    destination_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__: Any = (
        UniqueConstraint("tenant_id", "event_type", name="notification_route_idx"),
        {"schema": "notifications"},
    )


class InAppNotification(NotificationBase, TimestampMixin):
    __tablename__ = "in_app_notifications"
    ID_PREFIX = "notif_inapp"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, server_default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__: Any = (
        Index("ix_in_app_notif_tenant_user_read", "tenant_id", "user_id", "is_read", "created_at"),
        {"schema": "notifications"},
    )
