"""Pure header factory for Landis+Gyr Gridstream REST API."""

from __future__ import annotations

from ip.solutions.domains.energy.building_blocks.protocol_headers import (
    build_landis_headers as _build_landis_headers,
)


def build_landis_headers(api_version: str = "v2") -> dict[str, str]:
    """Pure header factory for Landis+Gyr Gridstream REST queries."""
    return _build_landis_headers(api_version=api_version)


__all__ = ["build_landis_headers"]
