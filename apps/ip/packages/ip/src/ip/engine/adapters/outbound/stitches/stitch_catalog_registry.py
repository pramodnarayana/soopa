"""In-memory adapter implementing StitchCatalogRegistryPort."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.domain.stitch import StitchSubscription
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)


class InMemoryStitchCatalogRegistry(StitchCatalogRegistryPort):
    """Stores StitchSubscriptions keyed by `(tenant_id, canonical_event_type)`."""

    def __init__(self) -> None:
        self._subscriptions: list[StitchSubscription] = []

    def register_subscription(self, subscription: StitchSubscription) -> None:
        self._subscriptions = [s for s in self._subscriptions if s.id != subscription.id]
        self._subscriptions.append(subscription)

    def list_subscriptions_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> Sequence[StitchSubscription]:
        return tuple(
            s
            for s in self._subscriptions
            if s.tenant_id in (tenant_id, "*")
            and s.canonical_event_type == canonical_event_type
            and s.is_active
        )


__all__ = ["InMemoryStitchCatalogRegistry"]
