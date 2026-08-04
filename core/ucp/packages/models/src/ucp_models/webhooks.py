from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_orm.models.common import TimestampMixin
from platform_orm.models.core import UcpBase
from database.models.replicated_mixins import WebhookMixin


class Webhook(UcpBase, WebhookMixin, TimestampMixin):
    __tablename__ = "webhooks"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
