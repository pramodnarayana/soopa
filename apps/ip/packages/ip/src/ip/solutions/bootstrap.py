"""Solution-layer IoC bootstrap wiring vertical domain plugins into the generic IP Engine."""

from __future__ import annotations

from collections.abc import Mapping

from database.router import DatabaseRouterPort
from dependency_injector import providers
from fastapi import FastAPI
from pubsub.ports.message_consumer_port import MessageConsumerPort
from shttp import HttpRequestAuthenticator
from sqlalchemy.ext.asyncio import AsyncSession

from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.bootstrap.api_provider import IpApiProvider
from ip.engine.bootstrap.container import (
    Container,
    DomainRepositoryFactory,
    create_engine_catalog_registry,
    create_ip_data_plane_uow,
)
from ip.engine.bootstrap.workers.ip_delivery_worker import IpDeliveryWorkerModule
from ip.engine.bootstrap.workers.ip_orchestrator_worker import IpOrchestratorWorkerModule
from ip.engine.domain.normalization.registries import CanonicalWriterRegistry
from ip.engine.ports.outbound.auth_resolver_port import AuthStrategyResolverPort
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from ip.engine.settings import IpEngineSettings
from ip.solutions.connectors.registry_loader import register_solution_connectors
from ip.solutions.connectors.sandbox.universal.router import (
    router as universal_simulator_router,
)
from ip.solutions.domains.energy.ports import (
    ENERGY_DOMAIN_REPOSITORY_KEY,
    EnergyDomainRepositoryPort,
)
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.solutions.domains.energy.writers import create_default_canonical_writer_registry
from ip.solutions.domains.tms.ports import TMS_DOMAIN_REPOSITORY_KEY
from ip.solutions.domains.tms.repository import SqlAlchemyTmsDomainRepository
from ip.solutions.stitches.registry_loader import (
    create_default_workflow_definition_registry,
    register_default_stitches,
)
from ip.solutions.transformers.registry_loader import create_default_transformer_registry

SOLUTION_DOMAIN_REPOSITORY_FACTORIES: Mapping[str, DomainRepositoryFactory] = {
    ENERGY_DOMAIN_REPOSITORY_KEY.name: SqlAlchemyEnergyDomainRepository,
    TMS_DOMAIN_REPOSITORY_KEY.name: SqlAlchemyTmsDomainRepository,
}


def resolve_energy_domain_repo(
    uow: IpDataPlaneUnitOfWorkPort,
) -> EnergyDomainRepositoryPort | None:
    """Resolves EnergyDomainRepositoryPort from IpDataPlaneUnitOfWorkPort without downcasting."""
    return uow.resolve_domain_repository(ENERGY_DOMAIN_REPOSITORY_KEY)


def create_solution_catalog_registry(
    allow_private_ips: bool = False,
    *,
    auth_resolver: AuthStrategyResolverPort[HttpRequestAuthenticator] | None = None,
) -> ConnectorCatalogRegistry:
    """Composes the pure engine protocol catalog registry with built-in solution connectors."""
    registry = create_engine_catalog_registry(
        allow_private_ips=allow_private_ips,
        auth_resolver=auth_resolver,
    )
    register_solution_connectors(registry)
    return registry


def create_solution_stitch_catalog() -> InMemoryStitchCatalogRegistry:
    """Creates an InMemoryStitchCatalogRegistry populated with built-in vertical stitches."""
    registry = InMemoryStitchCatalogRegistry()
    register_default_stitches(registry)
    return registry


def create_solution_canonical_writer_registry() -> CanonicalWriterRegistry[CanonicalWriterPort]:
    """Creates a CanonicalWriterRegistry populated with built-in vertical domain writers."""
    return create_default_canonical_writer_registry(repo_factory=resolve_energy_domain_repo)


def create_solution_data_plane_uow(
    tenant_session: AsyncSession,
    storage: TieredStoragePort | None = None,
) -> SqlAlchemyIpDataPlaneUnitOfWork:
    """Creates a Data Plane UoW pre-configured with registered solution domain repositories."""
    return create_ip_data_plane_uow(
        tenant_session,
        storage=storage,
        domain_repository_factories=SOLUTION_DOMAIN_REPOSITORY_FACTORIES,
    )


def configure_solution_container(container: Container) -> Container:
    """Injects built-in SaaS connectors, vertical domains, transformers, and stitches into `Container`."""
    container.domain_repository_factories.override(
        providers.Object(SOLUTION_DOMAIN_REPOSITORY_FACTORIES)
    )
    container.catalog_registry.override(
        providers.Factory(
            create_solution_catalog_registry,
            allow_private_ips=container.config.allow_private_ips.as_(bool),
            auth_resolver=container.auth_resolver,
        )
    )
    container.transformer_registry.override(
        providers.Singleton(create_default_transformer_registry)
    )
    container.writer_registry.override(
        providers.Singleton(create_solution_canonical_writer_registry)
    )
    container.stitch_catalog.override(providers.Singleton(create_solution_stitch_catalog))
    container.workflow_definition_registry.override(
        providers.Singleton(create_default_workflow_definition_registry)
    )
    return container


def create_solution_api_provider() -> IpApiProvider:
    """Creates an IpApiProvider wired with all built-in vertical solution registries."""
    return IpApiProvider(
        catalog_registry_factory=lambda allow_private_ips: create_solution_catalog_registry(
            allow_private_ips=allow_private_ips
        ),
        transformer_registry_factory=create_default_transformer_registry,
        stitch_catalog_factory=create_solution_stitch_catalog,
        workflow_definition_registry_factory=create_default_workflow_definition_registry,
        domain_repository_factories=SOLUTION_DOMAIN_REPOSITORY_FACTORIES,
    )


def register_solution_routes(app: FastAPI) -> None:
    """Registers solution-layer HTTP routers (such as Sandbox Simulator webhook triggers) onto `app`."""
    app.include_router(universal_simulator_router)


class IpSolutionOrchestratorWorkerModule(IpOrchestratorWorkerModule):
    """LaunchableWorker composition root for `ip-orchestrator-worker` wired with vertical solutions."""

    def __init__(
        self,
        settings: IpEngineSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
        realtime_consumer: MessageConsumerPort | None = None,
        bulk_consumer: MessageConsumerPort | None = None,
    ) -> None:
        super().__init__(
            settings,
            db_router=db_router,
            realtime_consumer=realtime_consumer,
            bulk_consumer=bulk_consumer,
            container_configurator=configure_solution_container,
        )


class IpSolutionDeliveryWorkerModule(IpDeliveryWorkerModule):
    """LaunchableWorker composition root for `ip-delivery-worker` wired with vertical solutions."""

    def __init__(
        self,
        settings: IpEngineSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
        realtime_consumer: MessageConsumerPort | None = None,
        bulk_consumer: MessageConsumerPort | None = None,
    ) -> None:
        super().__init__(
            settings,
            db_router=db_router,
            realtime_consumer=realtime_consumer,
            bulk_consumer=bulk_consumer,
            container_configurator=configure_solution_container,
        )


__all__ = [
    "SOLUTION_DOMAIN_REPOSITORY_FACTORIES",
    "IpSolutionDeliveryWorkerModule",
    "IpSolutionOrchestratorWorkerModule",
    "configure_solution_container",
    "create_solution_api_provider",
    "create_solution_canonical_writer_registry",
    "create_solution_catalog_registry",
    "create_solution_data_plane_uow",
    "create_solution_stitch_catalog",
    "register_solution_routes",
    "resolve_energy_domain_repo",
]
