from abc import ABC, abstractmethod

from edi.domain.types import AstNode, JsonDict


class BaseEnvelopeBuilder(ABC):
    """
    Abstract Base Class (Interface) for EDI Envelope Builders.
    Enforces that all standards (X12, EDIFACT, etc.) implement the build method.
    """

    @staticmethod
    @abstractmethod
    def build(route_config: JsonDict, payload: AstNode | list[AstNode]) -> AstNode:
        """
        Dynamically constructs the Abstract Syntax Tree (AST) for the given payload and route.
        """
