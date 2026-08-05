from typing import Any

from sqlalchemy.orm import DeclarativeBase, registry

GlobalRegistry = registry()
PlatformRegistry = GlobalRegistry
UcpRegistry = GlobalRegistry


class PlatformBase(DeclarativeBase):
    """
    Base class for Platform infrastructure models (Identity, Scheduling).
    """

    registry = PlatformRegistry
    __table_args__: Any = {"schema": "platform"}


class UcpBase(DeclarativeBase):
    """
    Base class for UCP (Global Control Plane) models.
    """

    registry = UcpRegistry
    __table_args__: Any = {"schema": "ucp"}
