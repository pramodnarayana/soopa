from edi.application.dtos.trace import EdiTraceDTO
from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class GetEdiTraceUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def get_edi_trace(
        self, tenant_id: str, trace_id: str, _routing_resolver: object | None = None
    ) -> EdiTraceDTO:
        """
        Get details for a specific trace lifecycle.
        """
        result = await self.uow.traces.get_edi_trace(tenant_id, trace_id)
        # A trace is valid if ANY of its composite parts exist. Outbound replay creates
        # EdiJson first; the EdiMessage is written asynchronously by the transform worker.
        # Raising 404 solely on missing EdiMessage would break the race window.
        if not result:
            raise TransactionNotFoundError(trace_id=trace_id)

        # Optional: Resolve trading partner name if resolver is provided
        # We can mutate the returned DTO lightly or return a richer response model
        # if the UI needs it, but the base DTO is EdiTraceDTO.

        return result
