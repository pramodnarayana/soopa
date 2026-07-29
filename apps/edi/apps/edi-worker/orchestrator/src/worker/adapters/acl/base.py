from abc import ABC, abstractmethod
from typing import Any


class EventTranslator(ABC):
    """
    Abstract Base Class for translating external domain events into
    internal EDI domain events.
    """

    @abstractmethod
    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        """
        Translates an external event payload to an internal event payload.

        Args:
            external_payload: The raw JSON body of the external event.

        Returns:
            A dictionary representing the internal SQS message structure expected by the Orchestrator.
        """
        pass
