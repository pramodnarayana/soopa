from sqlalchemy.orm import DeclarativeBase

from database.models.core import GlobalRegistry


class EdiGlobalBase(DeclarativeBase):
    registry = GlobalRegistry
    from typing import Any

    __table_args__: Any = {"schema": "edi"}
