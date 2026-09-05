from seedwork.domain.types import JsonValue
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.models.common import TimestampMixin
from database.models.core import IdentityBase


class PlatformSettings(IdentityBase, TimestampMixin):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
