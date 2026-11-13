from typing import Protocol

from seedwork.domain.exceptions import Result

from ucp.application.dto.shard_allocation import ShardAllocationProblem
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class ShardAllocationStrategyPort(Protocol):
    """Strategy port assigning a tenant+app subscription to an isolated or pooled physical cell."""

    async def allocate_shard_for_app(
        self,
        uow: UcpUnitOfWorkPort,
        tenant_id: str,
        app_id: str,
        app_slug: str,
    ) -> Result[str, ShardAllocationProblem]:
        """Dynamically evaluates shard topology and returns a selected active shard_id.

        Guarantees:
        1. Idempotency: Returns existing shard_id if tenant is already allocated.
        2. Concurrency safety: Mitigates thundering herds via P2C / jittered least-loaded selection.
        3. Transactional safety: Executes within the provided UoW session.
        """
        ...
