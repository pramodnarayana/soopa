"""
Null Object implementation for AS2DeliveryPort.

Used when AS2 delivery is not configured for a worker deployment.
Allows DeliveryService to always require a concrete AS2DeliveryPort
(no Optional[]) while still supporting webhook-only or SFTP-only deployments
without any conditional logic at the injection site.
"""

import structlog

from pipeline.ports.as2 import AS2DeliveryPort

logger = structlog.get_logger(__name__)


class NullAS2DeliveryAdapter(AS2DeliveryPort):
    """
    Null Object — raises RuntimeError on any attempt to use AS2 delivery.
    Inject this when the worker is known not to need AS2.

    Prefer this over injecting `None` — it gives a clear, descriptive error
    at the point of incorrect use rather than an AttributeError.
    """

    async def deliver(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        raise RuntimeError("NullAS2DeliveryAdapter used in production wiring!")
