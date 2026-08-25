import os

from platform_orm.models.common import OutboxMixin, SoftDeleteMixin, TimestampMixin
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from .base import EdiGlobalBase
from .replicated_mixins import (
    AS2PartnerMixin,
    AS2PartnershipMixin,
    InboundRouteMixin,
    OutboundEdiHeaderMixin,
    OutboundRouteMixin,
    SFTPPartnerMixin,
)


class AS2Partner(EdiGlobalBase, AS2PartnerMixin, TimestampMixin):
    """
    Global AS2 Partners (both our local gateway config, and remote shared configs).
    """

    __tablename__ = "as2_partners"

    tenant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )  # Null if shared global

    __table_args__ = (
        UniqueConstraint("tenant_id", "as2_id", name="uq_tenant_as2_id"),
        Index(
            "uq_global_as2_id", "as2_id", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
        {"schema": "edi"},
    )


class AS2Partnership(EdiGlobalBase, AS2PartnershipMixin, TimestampMixin):
    """
    OpenAS2 style Partnership (links Local Partner to Remote Partner)
    and stores all MDN and Encryption properties.
    """

    __tablename__ = "as2_partnerships"

    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    local_partner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("local_partner_id", "remote_partner_id", name="uq_as2_partnership"),
        {"schema": "edi"},
    )


class SFTPPartner(EdiGlobalBase, SFTPPartnerMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sftp_partners"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)


class InboundRoute(EdiGlobalBase, InboundRouteMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inbound_routes"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    webhook_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    as2_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.sftp_partners.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(webhook_id IS NOT NULL)::int + (as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
            name="chk_inbound_routes_exactly_one_dest",
        ),
        Index(
            "ix_inbound_routes_unique_active",
            "tenant_id",
            "isa_sender_id",
            "isa_receiver_id",
            "transaction_type",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        {"schema": "edi"},
    )


class OutboundRoute(EdiGlobalBase, OutboundRouteMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "outbound_routes"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    as2_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.sftp_partners.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
            name="chk_outbound_routes_exactly_one_dest",
        ),
        Index(
            "ix_outbound_routes_unique_trading_partner_id",
            "tenant_id",
            "trading_partner_id",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        {"schema": "edi"},
    )


class OutboundEdiHeader(EdiGlobalBase, OutboundEdiHeaderMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "outbound_edi_headers"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_outbound_edi_headers_unique_trading_partner_id",
            "tenant_id",
            "trading_partner_id",
            unique=True,
        ),
        {"schema": "edi"},
    )


class ControlPlaneOutbox(EdiGlobalBase, OutboxMixin):
    __tablename__ = "outbox"
    ID_PREFIX = "cp_edi_ob"

    id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        default=lambda: f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}",
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_global_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "edi"},
    )
