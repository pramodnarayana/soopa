import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError, RouteNotFoundEdiError
from edi.domain.routing.enums import EdiDirection
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, route_id: str, idempotency_key: str | None = None
    ) -> Result[None, EdiError]:
        aggregate = await self.uow.outbound_routes.get_outbound_route(tenant_id, route_id)
        if not aggregate:
            not_found = RouteNotFoundEdiError.for_id(
                route_id, direction=EdiDirection.OUTBOUND.value
            )
            logger.error(
                "outbound_route_delete_not_found",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        del_res = aggregate.mark_deleted(idempotency_key=idempotency_key)
        if del_res.is_err:
            domain_err = del_res.unwrap_err()
            logger.error(
                "outbound_route_delete_rejected",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.outbound_routes.delete(aggregate)

        logger.info(
            "outbound_route_deleted",
            route_id=route_id,
            tenant_id=tenant_id,
        )

        return Result.ok(None)
