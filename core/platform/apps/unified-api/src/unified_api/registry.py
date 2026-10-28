"""Dynamic API module registry for the Unified API Host Shell."""

from __future__ import annotations

import importlib
from typing import cast

import structlog
from seedwork.infra.api import LaunchableApiModule

logger = structlog.get_logger(__name__)

# Ordered so inline router modules ("ip") are registered before catch-all sub-app mounts ("edi").
API_MODULE_REGISTRY: dict[str, str] = {
    "ip": "ip.engine.adapters.inbound.api.module.IpApiModule",
    "edi": "edi.module.EdiApiModule",
}

CANONICAL_MODULE_ORDER: tuple[str, ...] = ("ip", "edi")


def get_api_module_instance(app_name: str) -> LaunchableApiModule:
    """Dynamically loads and instantiates a LaunchableApiModule by its canonical name."""
    normalized = app_name.strip().lower()
    if normalized not in API_MODULE_REGISTRY:
        raise ValueError(
            f"Unknown API module '{app_name}'. Valid options: {', '.join(API_MODULE_REGISTRY)}"
        )

    target_fqn = API_MODULE_REGISTRY[normalized]
    module_path, class_name = target_fqn.rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
        module_class = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"Failed to load API module class {target_fqn}: {exc}") from exc

    instance = module_class()
    return cast(LaunchableApiModule, instance)


def parse_enabled_app_names(enabled_apps: str) -> tuple[str, ...]:
    """Parses a comma-separated ENABLED_APPS string into canonical registration order."""
    requested = {
        token.strip().lower()
        for token in enabled_apps.split(",")
        if token.strip() and token.strip().lower() != "platform"
    }
    unknown = requested - set(API_MODULE_REGISTRY)
    if unknown:
        raise ValueError(
            f"Unknown API module(s) in ENABLED_APPS: {', '.join(sorted(unknown))}. "
            f"Valid options: {', '.join(API_MODULE_REGISTRY)}"
        )
    return tuple(name for name in CANONICAL_MODULE_ORDER if name in requested)


def load_enabled_api_modules(enabled_apps: str) -> list[LaunchableApiModule]:
    """Loads all enabled LaunchableApiModule instances in canonical registration order."""
    app_names = parse_enabled_app_names(enabled_apps)
    modules = [get_api_module_instance(name) for name in app_names]
    logger.info("unified_api_modules_loaded", enabled_apps=list(app_names))
    return modules


__all__ = [
    "API_MODULE_REGISTRY",
    "CANONICAL_MODULE_ORDER",
    "get_api_module_instance",
    "load_enabled_api_modules",
    "parse_enabled_app_names",
]
