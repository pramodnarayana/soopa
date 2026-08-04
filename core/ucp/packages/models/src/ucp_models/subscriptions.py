
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_orm.models.core import UcpBase


class App(UcpBase):
    __tablename__ = "apps"
    ID_PREFIX = "app"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class AppSubscription(UcpBase):
    __tablename__ = "app_subscriptions"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), primary_key=True
    )
    tier: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")
