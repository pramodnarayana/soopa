"""SQLAlchemy ORM model for `ip.simulator_entities` (`global_db`, schema `ip`)."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from ip.engine.adapters.outbound.database.models.base import IpGlobalBase
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionRecord
from ip.solutions.connectors.sandbox.universal.dto import SIMULATOR_ENTITY_ID_PREFIX
from ip.solutions.connectors.sandbox.universal.spec import (
    DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS,
    DEFAULT_SIMULATOR_RECORDS_PER_PULL,
    StreamVelocityMode,
)
from seedwork.domain.types import JsonDict, JsonValue
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class SimulatorEntityRecord(IpGlobalBase):
    """Database record representation of the `ip.simulator_entities` table."""

    ID_PREFIX: ClassVar[str] = SIMULATOR_ENTITY_ID_PREFIX

    __tablename__ = "simulator_entities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "entity_name",
            name="uq_ip_simulator_entity_conn_name",
        ),
        Index(
            "idx_ip_simulator_entities_tenant_conn",
            "tenant_id",
            "connection_id",
        ),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(ConnectionRecord.id, ondelete="CASCADE"),
        nullable=False,
    )
    entity_name: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_key_field: Mapped[str] = mapped_column(String(128), nullable=False)
    cursor_field: Mapped[str] = mapped_column(String(128), nullable=False)
    records_per_pull: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_SIMULATOR_RECORDS_PER_PULL
    )
    cursor_step_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS
    )
    velocity_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=StreamVelocityMode.ENTITY_TRANSACTIONAL.value,
    )
    sample_blueprint: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)
    inferred_json_schema: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    chaos_policy: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["SimulatorEntityRecord"]
