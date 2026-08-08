from ucp.ports.outbound.edi_service import IEdiService


class UcpAdapter(IEdiService):
    """
    Inbound adapter for the EDI domain.
    This class implements the contract defined by the UCP domain's IEdiService port.
    It translates UCP requests into internal EDI application service calls.
    """

    async def get_trading_partner_count(self, tenant_id: str) -> int:
        # In a real implementation, this would inject an EDI Use Case or Repository
        # and query the actual trading partner count.
        # For now, it returns a stub to prove the cross-domain contract wiring.
        return 0
