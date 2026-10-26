"""Integration Platform (IP) Domain Startup and Shutdown Hooks.

These hooks initialize and tear down IP infrastructure resources and IoC container state.
They are called by the Shell's lifespan (`unified_api/bootstrap/lifespan.py`).
"""

from __future__ import annotations

import os

import aioboto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from database.router import DatabaseRouterPort
from dependency_injector import providers
from fastapi import FastAPI

from ip.bootstrap.container import Container
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    DEFAULT_IP_PAYLOAD_BUCKET,
)

logger = structlog.get_logger(__name__)

_ip_container: Container | None = None


async def _ensure_payload_bucket(bucket_name: str = DEFAULT_IP_PAYLOAD_BUCKET) -> None:
    """Ensures the IP payload bucket exists when running against a local S3 endpoint."""
    endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("AWS_ENDPOINT_URL")
    if not endpoint_url:
        return
    session = aioboto3.Session()
    try:
        async with session.client(
            "s3",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            endpoint_url=endpoint_url,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        ) as s3:
            await s3.create_bucket(Bucket=bucket_name)
    except (ClientError, BotoCoreError, OSError) as exc:
        logger.info(
            "ip_s3_bucket_init_skipped",
            bucket=bucket_name,
            reason=str(exc),
        )


async def startup(
    app: FastAPI,
    *,
    db_router: DatabaseRouterPort,
    allow_private_ips: bool = False,
) -> None:
    """Initializes the IP IoC Container and IpTenantResolver and attaches them to `app.state`."""
    global _ip_container

    logger.info("ip_startup_initializing")
    await _ensure_payload_bucket(DEFAULT_IP_PAYLOAD_BUCKET)

    resolver = IpTenantResolver(db_router)
    app.state.ip_tenant_resolver = resolver

    container = Container()
    container.config.allow_private_ips.from_value(allow_private_ips)
    container.tenant_resolver.override(providers.Object(resolver))
    container.db_router.override(providers.Object(db_router))
    app.state.ip_container = container
    _ip_container = container
    logger.info("ip_startup_completed")


async def shutdown(app: FastAPI | None = None) -> None:
    """Gracefully cleans up IP container and resolver state on application shutdown."""
    global _ip_container

    logger.info("ip_shutdown_started")
    if app is not None and hasattr(app, "state"):
        app.state.ip_container = None
        app.state.ip_tenant_resolver = None
    _ip_container = None
    logger.info("ip_shutdown_completed")
