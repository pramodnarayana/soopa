import abc

from identity.domain.authorization import CapabilityDescriptor


class CapabilityRepositoryPort(abc.ABC):
    """
    Outbound port for querying the enterprise Capability / Permission Catalog.
    """

    @abc.abstractmethod
    async def list_all(self) -> list[CapabilityDescriptor]:
        """
        Fetch all capability descriptors registered in the catalog,
        ordered by domain and resource.
        """

    @abc.abstractmethod
    async def list_by_domain(self, domain: str) -> list[CapabilityDescriptor]:
        """
        Fetch all capability descriptors belonging to a specific domain (e.g., 'ip', 'identity').
        """

    @abc.abstractmethod
    async def get_by_code(self, code: str) -> CapabilityDescriptor | None:
        """
        Fetch a specific capability descriptor by its unique code.
        """
