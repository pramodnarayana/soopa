from database.models.replicated_mixins import WebhookMixin
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from platform_orm.models.common import SoftDeleteMixin, TimestampMixin
from platform_orm.models.core import UcpBase


class Webhook(UcpBase, WebhookMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "webhooks"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
