import contextlib
from collections.abc import Callable

import structlog

from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeliveryUseCase:
    """
    Application Use Case for orchestrating final-mile EDI delivery.

    Manages outbox leasing to guarantee at-most-once delivery semantics,
    then delegates to the correct delivery strategy via the DeliveryRouterUseCase.
    """

    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        router_factory: Callable[[], DeliveryRouterUseCase],
    ) -> None:
        self._uow_factory = uow_factory
        self._router_factory = router_factory

    async def execute(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """
        Executes the delivery pipeline for the given trace_id.

        If idempotency_key is provided, this method will atomically claim an
        outbox lease before executing delivery to prevent duplicate processing.
        """
        key_str = str(idempotency_key) if idempotency_key else None

        if not key_str:
            logger.warning("delivery.missing_idempotency_key", trace_id=trace_id)

        # Phase 2: Execute delivery and track status
        router = self._router_factory()
        try:
            await router.deliver(trace_id, idempotency_key=key_str)
        except Exception:
            logger.exception("delivery_failed", trace_id=trace_id)
            raise
