"""Integration Platform (IP) Engine Startup and Shutdown Hooks.

These hooks initialize and tear down pure IP IoC container state on `app.state`.
They are invoked by the Shell's lifespan (`unified_api/bootstrap/lifespan.py`).
All physical infrastructure provisioning (such as S3 buckets and SQS queues) is
managed declaratively via IaC (`topology.json` / Terraform), never at HTTP startup.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from database.router import DatabaseRouterPort
from dependency_injector import providers
from fastapi import FastAPI

from ip.engine.bootstrap.container import Container, create_ip_tenant_resolver

logger = structlog.get_logger(__name__)


async def startup(
    app: FastAPI,
    *,
    db_router: DatabaseRouterPort,
    allow_private_ips: bool = False,
    container_configurator: Callable[[Container], object] | None = None,
) -> None:
    """Initializes the IP IoC Container and tenant resolver and attaches them to `app.state`."""
    logger.info("ip_startup_initializing")

    resolver = create_ip_tenant_resolver(db_router)
    app.state.ip_tenant_resolver = resolver

    container = Container()
    container.config.allow_private_ips.from_value(allow_private_ips)
    container.tenant_resolver.override(providers.Object(resolver))
    container.db_router.override(providers.Object(db_router))
    if container_configurator is not None:
        container_configurator(container)
    app.state.ip_container = container
    app.state.ip_tiered_storage = container.tiered_storage()
    app.state.ip_transformer_registry = container.transformer_registry()
    app.state.ip_stitch_catalog = container.stitch_catalog()
    app.state.ip_workflow_definitions = container.workflow_definition_registry()
    app.state.ip_token_refresh_lock = container.token_refresh_lock()
    app.state.ip_token_refresher = container.oauth2_token_refresher()
    logger.info("ip_startup_completed")


async def shutdown(app: FastAPI | None = None) -> None:
    """Gracefully cleans up IP container and resolver state on application shutdown."""
    logger.info("ip_shutdown_started")
    if app is not None:
        app.state.ip_container = None
        app.state.ip_tenant_resolver = None
        app.state.ip_tiered_storage = None
        app.state.ip_transformer_registry = None
        app.state.ip_stitch_catalog = None
        app.state.ip_workflow_definitions = None
        app.state.ip_token_refresh_lock = None
        app.state.ip_token_refresher = None
    logger.info("ip_shutdown_completed")
