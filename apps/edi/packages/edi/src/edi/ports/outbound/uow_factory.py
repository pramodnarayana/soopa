import contextlib
from typing import Protocol

from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class DataPlaneUnitOfWorkFactoryPort(Protocol):
    """
    Abstract Factory for acquiring a Data Plane Unit of Work dynamically based on tenant identity.
    """

    def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]:
        """
        Retrieves a scoped Unit of Work for a given tenant and application.
        """
        ...
