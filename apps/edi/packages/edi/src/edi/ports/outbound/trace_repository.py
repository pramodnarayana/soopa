from typing import Protocol

from edi.application.dtos.trace import EdiTraceDTO


class TraceRepositoryPort(Protocol):
    """
    Port for the Trace Projection.
    Strictly responsible for reading the composite Trace view.
    """

    async def get_edi_trace(self, tenant_id: str, trace_id: str) -> EdiTraceDTO | None:
        """
        Retrieves the composite Trace (EdiMessage + EdiJsons + ApiGateways).
        Returns None if no matching trace is found.
        """
        ...
