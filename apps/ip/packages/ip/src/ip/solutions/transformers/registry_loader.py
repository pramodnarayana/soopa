"""Default L3 TransformerRegistry loader registering built-in Energy and TMS pure transformers."""

from __future__ import annotations

from ip.engine.domain.normalization.registries import TransformerRegistry
from ip.engine.ports.outbound.transformer_port import (
    TransformerPort,
    TransformerRegistryPort,
)
from ip.solutions.domains.energy.transformers.ami.meter_reading import (
    AmiMeterReadingTransformerV1,
    AmiMeterReadingTransformerV2,
)
from ip.solutions.domains.energy.transformers.ami.service_point import (
    AmiServicePointTransformerV1,
)
from ip.solutions.domains.energy.transformers.itron.meter_reading import (
    ItronMeterReadingTransformerV1,
)
from ip.solutions.domains.energy.transformers.itron.service_point import (
    ItronServicePointTransformerV1,
)
from ip.solutions.domains.tms.transformers import (
    MercuryGateCarrierTransformerV1,
    MercuryGateLoadTransformerV1,
    MercuryGateLoadTransformerV2,
)

_DEFAULT_ENERGY_TRANSFORMERS: tuple[TransformerPort, ...] = (
    AmiMeterReadingTransformerV1(),
    AmiMeterReadingTransformerV2(),
    AmiServicePointTransformerV1(),
    ItronMeterReadingTransformerV1(),
    ItronServicePointTransformerV1(),
)

_DEFAULT_TMS_TRANSFORMERS: tuple[TransformerPort, ...] = (
    MercuryGateLoadTransformerV1(),
    MercuryGateLoadTransformerV2(),
    MercuryGateCarrierTransformerV1(),
)


def register_default_transformers(registry: TransformerRegistryPort) -> None:
    """Register all built-in Energy and TMS pure transformers into the provided TransformerRegistryPort."""
    for transformer in (*_DEFAULT_ENERGY_TRANSFORMERS, *_DEFAULT_TMS_TRANSFORMERS):
        registry.register(transformer)


def create_default_transformer_registry() -> TransformerRegistry:
    """Create and populate a TransformerRegistry with all built-in domain transformers."""
    registry = TransformerRegistry()
    register_default_transformers(registry)
    return registry


__all__ = [
    "AmiMeterReadingTransformerV1",
    "AmiMeterReadingTransformerV2",
    "AmiServicePointTransformerV1",
    "ItronMeterReadingTransformerV1",
    "ItronServicePointTransformerV1",
    "MercuryGateCarrierTransformerV1",
    "MercuryGateLoadTransformerV1",
    "MercuryGateLoadTransformerV2",
    "create_default_transformer_registry",
    "register_default_transformers",
]
