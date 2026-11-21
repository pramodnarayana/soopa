"""HTTP and SOAP headers factory for Itron OpenWay AMI."""

from __future__ import annotations

from ip.solutions.domains.energy.building_blocks.protocol_headers import build_soap_headers


def build_itron_soap_headers(soap_action: str = "ExtractIntervalData") -> dict[str, str]:
    """Pure header factory for Itron OpenWay Collection Engine SOAP 1.2 requests."""
    return build_soap_headers(soap_action=soap_action)


__all__ = ["build_itron_soap_headers"]
