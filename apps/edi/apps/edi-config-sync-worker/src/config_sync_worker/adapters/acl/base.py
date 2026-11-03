from abc import ABC, abstractmethod

from seedwork.domain.types import JsonDict


class EventTranslator(ABC):
    """
    Abstract Base Class for translating external domain events into
    internal EDI domain events.
    """

    @abstractmethod
    def translate(self, external_payload: JsonDict) -> JsonDict:
        """
        Translates an external event payload to an internal event payload.

        Args:
            external_payload: The raw JSON body of the external event.

        Returns:
            A dictionary representing the internal SQS message structure expected by the Orchestrator.
        """
