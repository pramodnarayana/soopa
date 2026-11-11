"""Outer LaunchableApiModule Composition Root for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from fastapi import FastAPI

from ip.engine.module import IpApiModule as EngineIpApiModule
from ip.solutions.bootstrap import (
    configure_solution_container,
    create_solution_api_provider,
    register_solution_routes,
)


class IpApiModule(EngineIpApiModule):
    """API module assembling the generic IP Engine with built-in SaaS and vertical solutions."""

    def __init__(self) -> None:
        super().__init__(
            api_provider_factory=create_solution_api_provider,
            container_configurator=configure_solution_container,
        )

    def register_routes(self, app: FastAPI) -> None:
        super().register_routes(app)
        register_solution_routes(app)


__all__ = ["IpApiModule"]
