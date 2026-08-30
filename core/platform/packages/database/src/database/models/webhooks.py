import os

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.common import SoftDeleteMixin, TimestampMixin
from database.models.core import UcpBase


class Webhook(UcpBase, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "webhooks"
    ID_PREFIX = "ucp_cp_wh"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: f"wh_{os.urandom(12).hex()}"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_header_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
