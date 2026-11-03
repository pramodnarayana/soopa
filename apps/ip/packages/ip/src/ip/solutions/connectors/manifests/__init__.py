"""Built-in declarative manifests package."""

from __future__ import annotations

from ip.engine.domain.connection.http_spec import DeclarativeManifest
from ip.solutions.connectors.manifests.hubspot import HUBSPOT_MANIFEST
from ip.solutions.connectors.manifests.salesforce import SALESFORCE_MANIFEST
from ip.solutions.connectors.manifests.servicenow import SERVICENOW_MANIFEST
from ip.solutions.connectors.manifests.stripe import STRIPE_MANIFEST

BUILTIN_MANIFESTS: tuple[DeclarativeManifest, ...] = (
    SALESFORCE_MANIFEST,
    HUBSPOT_MANIFEST,
    STRIPE_MANIFEST,
    SERVICENOW_MANIFEST,
)

__all__ = [
    "BUILTIN_MANIFESTS",
    "HUBSPOT_MANIFEST",
    "SALESFORCE_MANIFEST",
    "SERVICENOW_MANIFEST",
    "STRIPE_MANIFEST",
]
