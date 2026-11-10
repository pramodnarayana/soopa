from datetime import UTC, datetime

from seedwork.utils import generate_id
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ucp.domain.constants import UcpIdPrefix

from database.constants import (
    VIRTUAL_BUCKET_RING_SIZE,
    DatabaseShardStatus,
    ShardRoutingStrategy,
)
from database.models.core import UcpBase


class DatabaseShard(UcpBase):
    __tablename__ = "database_shards"
    ID_PREFIX = UcpIdPrefix.SHARD.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    dsn: Mapped[str] = mapped_column(String(1024), nullable=False)
    reader_dsn: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    routing_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ShardRoutingStrategy.TENANT_REGISTRY.value,
        server_default=ShardRoutingStrategy.TENANT_REGISTRY.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DatabaseShardStatus.ACTIVE.value
    )


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
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=DatabaseShardStatus.ACTIVE.value
    )


class VirtualBucketAssignment(UcpBase):
    """Maps contiguous `[bucket_start, bucket_end]` consistent-hash ranges to Pods."""

    __tablename__ = "virtual_bucket_assignments"
    ID_PREFIX = UcpIdPrefix.BUCKET_ASSIGNMENT.value

    id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        default=lambda: generate_id(VirtualBucketAssignment.ID_PREFIX),
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), nullable=False
    )
    bucket_start: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_end: Mapped[int] = mapped_column(Integer, nullable=False)
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

    __table_args__ = (
        UniqueConstraint("app_id", "bucket_start", name="uq_virtual_bucket_app_start"),
        CheckConstraint(
            f"bucket_start >= 0 AND bucket_end >= bucket_start AND bucket_end < {VIRTUAL_BUCKET_RING_SIZE}",
            name="ck_virtual_bucket_bounds",
        ),
        {"schema": "ucp"},
    )
