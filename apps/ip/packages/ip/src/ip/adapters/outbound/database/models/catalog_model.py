"""SQLAlchemy ORM model for ip.connection_catalogs table."""

from datetime import datetime

from ip.adapters.outbound.database.models.base import IpBase
from ip.domain.types import JsonDict
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ConnectionCatalogRecord(IpBase):
    """Database record representation of the ip.connection_catalogs table."""

    __tablename__ = "connection_catalogs"
    __table_args__ = {"schema": "ip"}

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    catalog_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_definition: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
