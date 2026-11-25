"""Centralized SQLAlchemy Declarative Bases for Global Control Plane schemas."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, registry

GlobalRegistry = registry()
PlatformRegistry = GlobalRegistry
UcpRegistry = GlobalRegistry


class IdentityBase(DeclarativeBase):
    """Base class for Platform Identity infrastructure models."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "identity"}


class SchedulingBase(DeclarativeBase):
    """Base class for Platform Scheduling infrastructure models."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "scheduling"}


class PubSubBase(DeclarativeBase):
    """Base class for Platform Pub/Sub infrastructure models (durable queues & topic subscriptions)."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "pubsub"}


class ConfigSyncBase(DeclarativeBase):
    """Base class for Platform Control-to-Data-Plane Dynamic Watch models (`config_sync` schema)."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "config_sync"}


class NotificationBase(DeclarativeBase):
    """Base class for Platform Notification infrastructure models."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "notifications"}


class ObservabilityBase(DeclarativeBase):
    """Base class for Platform Observability infrastructure models."""

    registry = PlatformRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "observability"}


class UcpBase(DeclarativeBase):
    """Base class for UCP (Global Control Plane) models."""

    registry = UcpRegistry
    __table_args__: dict[str, object] | tuple[object, ...] = {"schema": "ucp"}
