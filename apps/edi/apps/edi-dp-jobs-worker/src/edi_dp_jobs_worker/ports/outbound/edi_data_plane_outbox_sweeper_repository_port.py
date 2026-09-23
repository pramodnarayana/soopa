from collections.abc import Sequence
from typing import Protocol

from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox


class EdiDataPlaneOutboxSweeperRepositoryPort(Protocol):
    """
    Port for fetching stranded data plane outbox events that were never processed.
    """

    async def fetch_stranded_outbox_events(self) -> Sequence[DataPlaneOutbox]:
        """
        Fetches events from the data plane outbox that are older than a threshold
        and have no corresponding entry in the events_processed table.
        """
        ...
