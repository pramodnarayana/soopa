"""Outbound port interface for persisting and reading StitchTaskConfig aggregates."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.stitch.stitch_task_config import StitchTaskConfig


class StitchTaskConfigRepositoryPort(Protocol):
    """Port interface for StitchTaskConfig persistence in the Control Plane."""

    async def get_by_node(
        self, tenant_id: str, stitch_id: str, node_key: str
    ) -> StitchTaskConfig | None:
        """Retrieves runtime task policy for a specific Stitch DAG node."""
        ...

    async def list_by_stitch(self, tenant_id: str, stitch_id: str) -> list[StitchTaskConfig]:
        """Lists all task runtime policies configured for a specific Stitch."""
        ...

    async def save(self, config: StitchTaskConfig) -> None:
        """Persists or updates the StitchTaskConfig aggregate and drains its domain events."""
        ...

    async def delete(
        self,
        tenant_id: str,
        stitch_id: str,
        node_key: str,
        config: StitchTaskConfig | None = None,
    ) -> bool:
        """Deletes runtime task policy for a DAG node and drains domain events. Returns True if deleted."""
        ...
