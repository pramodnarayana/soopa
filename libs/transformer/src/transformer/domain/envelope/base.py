from abc import ABC, abstractmethod
from typing import Any


class BaseEnvelopeBuilder(ABC):
    """
    Abstract Base Class (Interface) for EDI Envelope Builders.
    Enforces that all standards (X12, EDIFACT, etc.) implement the build method.
    """

    @staticmethod
    @abstractmethod
    def build(
        route_config: dict[str, Any], payload: dict[str, Any] | list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Dynamically constructs the Abstract Syntax Tree (AST) for the given payload and route.
        """
        pass
