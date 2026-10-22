"""Loader and bootstrap routines for the connector catalog registry."""

from __future__ import annotations

from ip.application.connectors.itron_mdm_connector import ItronMdmConnector
from ip.application.connectors.manifests import BUILTIN_MANIFESTS
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector


def register_builtin_connectors(
    registry: ConnectorCatalogRegistry, allow_private_ips: bool = False
) -> None:
    """Registers all built-in declarative manifests and native protocol connectors."""
    for manifest in BUILTIN_MANIFESTS:
        registry.register_manifest(manifest)

    itron = ItronMdmConnector(allow_private_ips=allow_private_ips)
    registry.register_connector(itron, ItronMdmConnector.default_catalog_summary())

    sftp = SftpConnector()
    registry.register_connector(sftp, SftpConnector.default_catalog_summary())


def create_default_catalog_registry(allow_private_ips: bool = False) -> ConnectorCatalogRegistry:
    """Creates and returns a ConnectorCatalogRegistry pre-seeded with built-in connectors."""
    registry = ConnectorCatalogRegistry(allow_private_ips=allow_private_ips)
    register_builtin_connectors(registry, allow_private_ips=allow_private_ips)
    return registry
