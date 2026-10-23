"""Loader and bootstrap routines for generic built-in connector catalog registry."""

from __future__ import annotations

from ip.application.connectors.manifests import BUILTIN_MANIFESTS
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector
from ip.engine.application.responses import CatalogAppSummaryDTO


def register_builtin_connectors(
    registry: ConnectorCatalogRegistry, allow_private_ips: bool = False
) -> None:
    """Registers built-in declarative manifests and standard native protocol connectors.

    Connectors remain pure protocol transports (HTTP, SFTP, etc.).
    Domain/vertical mappings belong exclusively in transformers.
    """
    for manifest in BUILTIN_MANIFESTS:
        registry.register_manifest(manifest)

    # 1. Universal HTTP / REST API Connector
    http_conn = GenericHttpConnector(app_id="http", allow_private_ips=allow_private_ips)
    registry.register_connector(
        http_conn,
        CatalogAppSummaryDTO(
            app_id="http",
            display_name="HTTP / REST API",
            category="API",
            auth_type="BEARER_TOKEN",
            description="Universal HTTP / REST API connector for SaaS and custom web endpoints.",
            connector_type="GENERIC_HTTP",
        ),
    )

    # 2. SFTP connector
    sftp = SftpConnector()
    registry.register_connector(sftp, SftpConnector.default_catalog_summary())


def create_default_catalog_registry(allow_private_ips: bool = False) -> ConnectorCatalogRegistry:
    """Creates and returns a ConnectorCatalogRegistry pre-seeded with built-in connectors."""
    registry = ConnectorCatalogRegistry(allow_private_ips=allow_private_ips)
    register_builtin_connectors(registry, allow_private_ips=allow_private_ips)
    return registry
