from typing import Any

from platform_orm.models.common import TimestampMixin
from platform_orm.models.core import IdentityBase
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column


class PlatformSettings(IdentityBase, TimestampMixin):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict[str, Any] | list[Any] | str | int | bool | None] = mapped_column(
        JSON, nullable=True
    )
