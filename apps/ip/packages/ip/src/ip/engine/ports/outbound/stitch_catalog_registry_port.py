"""Outbound port for discovering Stitches bound to L3 Canonical Events."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from orchestration.domain.run import WorkflowRun
from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.stitch import Stitch


class StitchCatalogRegistryPort(Protocol):
    """Port for registering and resolving active Stitches per tenant and canonical event type."""

    def register_stitch(self, stitch: Stitch) -> None: ...

    def list_stitches_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> Sequence[Stitch]: ...

    def list_stitches(
        self,
        *,
        tenant_id: str,
    ) -> Sequence[Stitch]: ...

    def get_stitch(
        self,
        *,
        tenant_id: str,
        stitch_id: str,
    ) -> Stitch | None: ...

    def find_any_stitch_by_id(
        self,
        *,
        stitch_id: str,
    ) -> Stitch | None: ...


class StitchShardGatewayPort(Protocol):
    """Outbound port for dispatching canonical events and querying WorkflowRuns on a tenant's Data Plane shard."""

    async def get_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Result[WorkflowRun, IpError]: ...

    async def dispatch_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
        event_id: str,
        payload: JsonDict,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> Result[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], IpError]: ...


__all__ = ["StitchCatalogRegistryPort", "StitchShardGatewayPort"]
