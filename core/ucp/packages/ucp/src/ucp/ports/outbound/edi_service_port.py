import abc


class EdiServicePort(abc.ABC):
    """
    Outbound Port for the UCP domain to synchronously communicate with the EDI domain.
    In a Modular Monolith, this is implemented by an Inbound Adapter in the EDI domain,
    allowing strict cross-domain contract enforcement without HTTP overhead.
    """

    @abc.abstractmethod
    async def get_trading_partner_count(self, tenant_id: str) -> int:
        """Returns the total number of trading partners for a given tenant."""
