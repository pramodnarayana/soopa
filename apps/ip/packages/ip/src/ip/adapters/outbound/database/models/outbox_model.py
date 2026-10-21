"""SQLAlchemy ORM model for ip.outbox table."""

from ip.adapters.outbound.database.models.base import IpBase
from seedwork.utils import generate_id
from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.common import OutboxMixin


class IpOutboxRecord(IpBase, OutboxMixin):
    """Transactional Outbox table for the Integration Platform bounded context."""

    __tablename__ = "outbox"
    ID_PREFIX = "ip_obx"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: generate_id(IpOutboxRecord.ID_PREFIX),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_ip_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "ip"},
    )
