"""
Bots global vars
"""
# pylint: disable=invalid-name

from bots_core.__about__ import __version__
from bots_core.application.ports.bots_db_port import IBotsDatabasePort

# Globals used by Bots
import sys
from typing import Any
from bots_core.infrastructure.config.context import get_context

class BotsGlobalProxy:
    """
    Enterprise-Grade Module Proxy that delegates all attribute access to the
    underlying ContextVar isolated per-request. This fully eliminates the legacy
    static mutable singleton pattern without breaking existing API contracts.
    """
    def __getattr__(self, name: str) -> Any:
        ctx = get_context()
        if hasattr(ctx, name):
            return getattr(ctx, name)
        raise AttributeError(f"module 'botsglobal' has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        ctx = get_context()
        if hasattr(ctx, name):
            setattr(ctx, name, value)
        else:
            raise AttributeError(f"module 'botsglobal' has no attribute '{name}'")

# Replace the module object in sys.modules to intercept all access.
sys.modules[__name__] = BotsGlobalProxy()
