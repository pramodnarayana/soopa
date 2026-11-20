"""Default L3 TransformerRegistry loader registering built-in Energy and TMS pure transformers."""

from __future__ import annotations

from ip.engine.domain.normalization.registries import TransformerRegistry
from ip.engine.ports.outbound.transformer_port import (
    TransformerPort,
    TransformerRegistryPort,
)
from ip.solutions.domains.energy.itron.meter_reading_transformer import (
    ItronMeterReadingTransformer,
)
from ip.solutions.domains.energy.itron.service_point_transformer import (
    ItronServicePointTransformer,
)
from ip.solutions.domains.energy.landis.meter_reading_transformer import (
    AmiMeterReadingTransformer,
    AmiMeterReadingTransformerV1,
    AmiMeterReadingTransformerV2,
)
from ip.solutions.domains.energy.landis.service_point_transformer import (
    AmiServicePointTransformer,
)
from ip.solutions.domains.energy.sap.billing_reading_transformer import (
    SapBillingReadingTransformer,
)
from ip.solutions.domains.tms.transformers import (
    MercuryGateCarrierTransformer,
    MercuryGateLoadTransformer,
)

_DEFAULT_ENERGY_TRANSFORMERS: tuple[TransformerPort, ...] = (
    AmiMeterReadingTransformerV1(),
    AmiMeterReadingTransformerV2(),
    AmiServicePointTransformer(),
    ItronMeterReadingTransformer(),
    ItronServicePointTransformer(),
    SapBillingReadingTransformer(),
)

_DEFAULT_TMS_TRANSFORMERS: tuple[TransformerPort, ...] = (
    MercuryGateLoadTransformer(),
    MercuryGateCarrierTransformer(),
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
    "AmiMeterReadingTransformer",
    "AmiMeterReadingTransformerV1",
    "AmiMeterReadingTransformerV2",
    "AmiServicePointTransformer",
    "ItronMeterReadingTransformer",
    "ItronServicePointTransformer",
    "MercuryGateCarrierTransformer",
    "MercuryGateLoadTransformer",
    "SapBillingReadingTransformer",
    "create_default_transformer_registry",
    "register_default_transformers",
]
