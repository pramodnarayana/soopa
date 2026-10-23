"""Declarative IoC Container for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from dependency_injector import containers, providers
from security.provider import SecurityProvider
from storage.provider import StorageProvider

from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    DEFAULT_IP_PAYLOAD_BUCKET,
    TieredStorageAdapter,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsUseCase,
)
from ip.engine.application.use_cases.replication.sweep_stale_replicas_use_case import (
    SweepStaleReplicasUseCase,
)
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry


class Container(containers.DeclarativeContainer):
    """Declarative IoC container for the Integration Platform bounded context."""

    config = providers.Configuration()

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    cipher = providers.Singleton(SecurityProvider.get_cipher)

    catalog_registry = providers.Factory(
        create_default_catalog_registry,
        allow_private_ips=config.allow_private_ips.as_(bool),
    )

    extractor_registry = providers.Singleton(RecordExtractorRegistry)

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
    cp_uow = providers.Factory(SqlAlchemyIpControlPlaneUnitOfWork)
    dp_uow = providers.Factory(SqlAlchemyIpDataPlaneUnitOfWork)
    dp_uow_provider = providers.Factory(IpTenantUoWProvider)

    # -----------------------------------------------------------------------
    # Replication Use Cases (Layer 2)
    # -----------------------------------------------------------------------
    replicate_records_use_case = providers.Factory(
        ReplicateRecordsUseCase,
        extractor_registry=extractor_registry,
        tiered_storage=tiered_storage,
    )
    sweep_stale_replicas_use_case = providers.Factory(SweepStaleReplicasUseCase)


__all__ = ["Container"]
