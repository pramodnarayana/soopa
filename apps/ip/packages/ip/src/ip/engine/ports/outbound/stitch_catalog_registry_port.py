"""Outbound port for discovering StitchSubscriptions bound to L3 Canonical Events."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.stitch import StitchSubscription


class StitchCatalogRegistryPort(Protocol):
    """Port for registering and resolving active StitchSubscriptions per tenant and canonical event type."""

    def register_subscription(self, subscription: StitchSubscription) -> None: ...

    def list_subscriptions_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> Sequence[StitchSubscription]: ...


__all__ = ["StitchCatalogRegistryPort"]
