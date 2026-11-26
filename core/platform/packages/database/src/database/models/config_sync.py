"""SQLAlchemy ORM model for the Universal Control-to-Data-Plane Dynamic Watch changelog (`config_sync` schema)."""

from __future__ import annotations

from datetime import UTC, datetime

from seedwork.domain.types import JsonDict
from sqlalchemy import BigInteger, DateTime, Identity, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from database.models.core import ConfigSyncBase


class Xid8(UserDefinedType[int]):
    """PostgreSQL 13+ 64-bit monotonic transaction identifier (`xid8`) without 32-bit wraparound."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        del kw
        return "xid8"


class ConfigChangelogEntry(ConfigSyncBase):
    """Append-only monotonically versioned changelog backing HTTPS Dynamic Watch catch-up & SSE streaming."""

    __tablename__ = "config_changelog"

    version: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    txid: Mapped[int] = mapped_column(
        Xid8(),
        server_default=text("pg_current_xact_id()"),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_config_changelog_app_tenant_version",
            "app_id",
            "tenant_id",
            "version",
        ),
        Index(
            "ix_config_changelog_txid_version",
            "txid",
            "version",
        ),
        Index(
            "ix_config_changelog_created_at",
            "created_at",
        ),
        {"schema": "config_sync"},
    )
