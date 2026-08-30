from datetime import UTC, datetime

from database.models.core import UcpBase
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class DatabaseShard(UcpBase):
    __tablename__ = "database_shards"
    ID_PREFIX = "ucp_shard"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    dsn: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


class ShardRegistry(UcpBase):
    __tablename__ = "shard_registry"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), primary_key=True
    )
    shard_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.database_shards.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
