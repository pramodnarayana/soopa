from typing import Any

from sqlalchemy.orm import DeclarativeBase, registry

GlobalRegistry = registry()
PlatformRegistry = GlobalRegistry
UcpRegistry = GlobalRegistry


class IdentityBase(DeclarativeBase):
    """
    Base class for Platform Identity infrastructure models.
    """

    registry = PlatformRegistry
    __table_args__: Any = {"schema": "identity"}


class SchedulingBase(DeclarativeBase):
    """
    Base class for Platform Scheduling infrastructure models.
    """

    registry = PlatformRegistry
    __table_args__: Any = {"schema": "scheduling"}


class NotificationBase(DeclarativeBase):
    """
    Base class for Platform Notification infrastructure models.
    """

    registry = PlatformRegistry
    __table_args__: Any = {"schema": "notifications"}


class ObservabilityBase(DeclarativeBase):
    """
    Base class for Platform Observability infrastructure models.
    """

    registry = PlatformRegistry
    __table_args__: Any = {"schema": "observability"}


class UcpBase(DeclarativeBase):
    """
    Base class for UCP (Global Control Plane) models.
    """

    registry = UcpRegistry
    __table_args__: Any = {"schema": "ucp"}
