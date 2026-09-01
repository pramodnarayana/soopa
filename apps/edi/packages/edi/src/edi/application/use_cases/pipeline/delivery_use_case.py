import contextlib
from collections.abc import Callable

import structlog

from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

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
        router_factory: Callable[[DataPlaneUnitOfWorkPort], DeliveryRouterUseCase],
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

        # Phase 1: Claim lease (in isolated short-lived transaction)
        owner_token: str | None = None
        if key_str:
            async with self._uow_factory() as uow, uow:
                owner_token = await uow.outbox.claim_delivery_outbox_event(key_str)
                if not owner_token:
                    logger.info(
                        "delivery.skipped_already_claimed",
                        idempotency_key=idempotency_key,
                    )
                    return
                await uow.commit()

        # Phase 2: Execute delivery in new transaction scope
        async with self._uow_factory() as uow, uow:
            router = self._router_factory(uow)
            try:
                await router.deliver(trace_id, idempotency_key=key_str)

                if key_str and owner_token:
                    await uow.outbox.mark_delivery_success(key_str, owner_token)

                await uow.commit()
            except Exception:
                if key_str and owner_token:
                    try:
                        await uow.rollback()
                        await uow.outbox.mark_delivery_failure(key_str, owner_token)
                        await uow.commit()
                    except Exception:
                        logger.exception(
                            "outbox_delivery_failure_mark_failed",
                            trace_id=trace_id,
                            idempotency_key=key_str,
                        )

                logger.exception("delivery_failed", trace_id=trace_id)
                raise
