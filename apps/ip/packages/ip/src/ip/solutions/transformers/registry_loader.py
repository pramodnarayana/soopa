"""Default L3 TransformerRegistry loader registering built-in Energy and TMS pure transformers."""

from __future__ import annotations

from ip.engine.domain.normalization.registries import TransformerRegistry
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.solutions.domains.energy.transformers import (
    AmiMeterReadingTransformerV1,
    AmiMeterReadingTransformerV2,
    AmiServicePointTransformerV1,
)
from ip.solutions.domains.tms.transformers import (
    MercuryGateCarrierTransformerV1,
    MercuryGateLoadTransformerV1,
    MercuryGateLoadTransformerV2,
)


def register_default_transformers(registry: TransformerRegistryPort) -> None:
    """Register all built-in Energy and TMS pure transformers into the provided TransformerRegistryPort."""
    registry.register(AmiMeterReadingTransformerV1())
    registry.register(AmiMeterReadingTransformerV2())
    registry.register(AmiServicePointTransformerV1())
    registry.register(MercuryGateLoadTransformerV1())
    registry.register(MercuryGateLoadTransformerV2())
    registry.register(MercuryGateCarrierTransformerV1())


def create_default_transformer_registry() -> TransformerRegistry:
    """Create and populate a TransformerRegistry with all built-in domain transformers."""
    registry = TransformerRegistry()
    register_default_transformers(registry)
    return registry


__all__ = [
    "AmiMeterReadingTransformerV1",
    "AmiMeterReadingTransformerV2",
    "AmiServicePointTransformerV1",
    "MercuryGateCarrierTransformerV1",
    "MercuryGateLoadTransformerV1",
    "MercuryGateLoadTransformerV2",
    "create_default_transformer_registry",
    "register_default_transformers",
]
