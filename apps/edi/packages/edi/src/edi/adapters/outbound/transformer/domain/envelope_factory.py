from seedwork.domain.types import JsonValue

from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder
from edi.adapters.outbound.transformer.domain.envelope.edifact import EdifactEnvelopeBuilder
from edi.adapters.outbound.transformer.domain.envelope.x12 import X12EnvelopeBuilder
from edi.domain.constants import EdiStandard
from edi.domain.types import AstNode


class EnvelopeFactory:
    """
    Enterprise-grade factory for dynamically constructing Abstract Syntax Trees (AST)
    for various EDI standards (X12, EDIFACT) based on Route Configurations.
    """

    _BUILDERS: dict[str, type[BaseEnvelopeBuilder]] = {
        EdiStandard.X12: X12EnvelopeBuilder,
        EdiStandard.EDIFACT: EdifactEnvelopeBuilder,
    }

    @staticmethod
    def build_ast(route_config: dict[str, JsonValue], payload: AstNode | list[AstNode]) -> AstNode:
        """
        Dynamically dispatches to the correct standard builder based on route config.
        """
        standard = str(route_config.get("default_standard", EdiStandard.X12)).lower().strip()

        builder = EnvelopeFactory._BUILDERS.get(standard)
        if not builder:
            raise ValueError(f"Unsupported EDI standard in Route Configuration: '{standard}'")

        return builder.build(route_config, payload)
