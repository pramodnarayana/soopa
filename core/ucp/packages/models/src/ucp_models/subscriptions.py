from datetime import UTC, datetime

from database.models.core import UcpBase
from seedwork.constants import LifecycleStatus
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column


class App(UcpBase):
    __tablename__ = "apps"
    ID_PREFIX = DomainIdPrefix.UCP_APP.value

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: generate_id(App.ID_PREFIX)
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    idp_project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )


class AppSubscription(UcpBase):
    __tablename__ = "app_subscriptions"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), primary_key=True
    )
    tier: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=LifecycleStatus.ACTIVE.value
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
        Index("idx_app_subs_tenant_status", "tenant_id", "status"),
        {"schema": "ucp"},
    )
