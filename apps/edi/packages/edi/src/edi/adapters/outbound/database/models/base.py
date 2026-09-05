from sqlalchemy.orm import DeclarativeBase

from database.models.core import GlobalRegistry


class EdiGlobalBase(DeclarativeBase):
    registry = GlobalRegistry

    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "edi"}
