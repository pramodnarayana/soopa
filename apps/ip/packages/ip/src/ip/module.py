"""Outer LaunchableApiModule Composition Root for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from fastapi import FastAPI

from ip.engine.module import IpApiModule as EngineIpApiModule
from ip.solutions.bootstrap import (
    SolutionDatabaseRuntime,
    configure_solution_container,
    create_solution_api_provider,
    register_solution_routes,
)


class IpApiModule(EngineIpApiModule):
    """API module assembling the generic IP Engine with built-in SaaS and vertical solutions."""

    def __init__(self) -> None:
        self._solution_runtime = SolutionDatabaseRuntime()
        super().__init__(
            api_provider_factory=lambda: create_solution_api_provider(self._solution_runtime),
            container_configurator=configure_solution_container,
        )

    def register_routes(self, app: FastAPI) -> None:
        self._solution_runtime.bind_app(app)
        super().register_routes(app)
        register_solution_routes(app)


__all__ = ["IpApiModule"]
