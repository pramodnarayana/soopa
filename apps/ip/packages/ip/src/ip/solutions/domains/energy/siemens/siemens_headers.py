"""Pure header factory for Siemens EnergyIP REST API."""

from __future__ import annotations

from ip.solutions.domains.energy.building_blocks.protocol_headers import (
    build_siemens_headers as _build_siemens_headers,
)


def build_siemens_headers(api_version: str = "v1") -> dict[str, str]:
    """Pure header factory for Siemens EnergyIP REST queries."""
    return _build_siemens_headers(api_version=api_version)


__all__ = ["build_siemens_headers"]
