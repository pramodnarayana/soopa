"""Outer LaunchableApiModule Composition Root for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from ip.engine.module import IpApiModule as EngineIpApiModule
from ip.solutions.bootstrap import configure_solution_container, create_solution_api_provider


class IpApiModule(EngineIpApiModule):
    """API module assembling the generic IP Engine with built-in SaaS and vertical solutions."""

    def __init__(self) -> None:
        super().__init__(
            api_provider_factory=create_solution_api_provider,
            container_configurator=configure_solution_container,
        )


__all__ = ["IpApiModule"]
