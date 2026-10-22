"""Declarative IoC Container for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from dependency_injector import containers, providers
from security.provider import SecurityProvider
from storage.provider import StorageProvider

from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    DEFAULT_IP_PAYLOAD_BUCKET,
    TieredStorageAdapter,
)


class Container(containers.DeclarativeContainer):
    """Declarative IoC container for the Integration Platform bounded context."""

    config = providers.Configuration()

    wiring_config = containers.WiringConfiguration(
        packages=[
            "unified_api.adapters.inbound.http.dependencies.ip",
        ]
    )

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    cipher = providers.Singleton(SecurityProvider.get_cipher)

    catalog_registry = providers.Factory(
        create_default_catalog_registry,
        allow_private_ips=config.allow_private_ips.as_(bool),
    )

    payload_storage = providers.Singleton(
        StorageProvider.create_payload_storage,
        bucket=DEFAULT_IP_PAYLOAD_BUCKET,
    )

    tiered_storage = providers.Singleton(
        TieredStorageAdapter,
        storage_client=payload_storage,
    )

    # -----------------------------------------------------------------------
    # Repositories and Units of Work
    # -----------------------------------------------------------------------
    tenant_resolver = providers.Dependency(instance_of=IpTenantResolver)
    cp_uow = providers.Factory(SqlAlchemyControlPlaneUnitOfWork)
    dp_uow = providers.Factory(SqlAlchemyDataPlaneUnitOfWork)
    dp_uow_provider = providers.Factory(IpTenantUoWProvider)


__all__ = ["Container"]
