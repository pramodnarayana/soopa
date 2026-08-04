from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_orm.models.common import TimestampMixin
from platform_orm.models.core import UcpBase


class PlatformSettings(UcpBase, TimestampMixin):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict[str, Any] | list[Any] | str | int | bool | None] = mapped_column(
        JSON, nullable=True
    )
