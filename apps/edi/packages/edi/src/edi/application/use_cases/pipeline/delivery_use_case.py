from collections.abc import Callable

import structlog

from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase

logger = structlog.get_logger(__name__)


class DeliveryUseCase:
    """
    Application Use Case for orchestrating final-mile EDI delivery.

    Deduplication is handled downstream by DeliveryRouterUseCase.deliver via
    record_idempotency, which writes an events_processed record atomically in the
    same transaction as the delivery outcome. This class is a thin orchestration
    layer that delegates routing to DeliveryRouterUseCase.
    """

    def __init__(
        self,
        router_factory: Callable[[], DeliveryRouterUseCase],
    ) -> None:
        self._router_factory = router_factory

    async def execute(self, trace_id: str, idempotency_key: str | None = None) -> None:
        """
        Executes the delivery pipeline for the given trace_id.

        If idempotency_key is provided, DeliveryRouterUseCase will record it
        in events_processed before executing delivery to prevent duplicate processing.
        """
        key_str = str(idempotency_key) if idempotency_key else None

        if not key_str:
            logger.warning("delivery.missing_idempotency_key", trace_id=trace_id)

        router = self._router_factory()
        try:
            await router.deliver(trace_id, idempotency_key=key_str)
        except Exception:
            logger.exception("delivery_failed", trace_id=trace_id)
            raise
