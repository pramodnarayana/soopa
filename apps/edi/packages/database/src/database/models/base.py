from platform_orm.models.core import GlobalRegistry
from sqlalchemy.orm import DeclarativeBase


class EdiGlobalBase(DeclarativeBase):
    registry = GlobalRegistry
    from typing import Any

    __table_args__: Any = {"schema": "edi"}
