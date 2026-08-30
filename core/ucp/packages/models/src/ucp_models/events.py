from typing import Any

from database.models.common import OutboxMixin
from database.models.core import UcpBase
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text


class ControlPlaneOutbox(UcpBase, OutboxMixin):
    __tablename__ = "outbox"
    ID_PREFIX = "ucp_cp_ob"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
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
