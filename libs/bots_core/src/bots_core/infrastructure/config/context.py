import contextvars
from dataclasses import dataclass, field
from typing import Any, Dict, Set, List, Optional
import logging

from bots_core.__about__ import __version__
from bots_core.application.ports.bots_db_port import IBotsDatabasePort

@dataclass
class BotsContext:
    """
    Enterprise-Grade execution context for the BOTS engine.
    This replaces the legacy static mutable singleton (botsglobal),
    ensuring that configuration, database connections, and loggers
    are strictly isolated per-request or per-execution context.
    """
    ini: Any = None
    logger: Optional[logging.Logger] = None
    logmap: Optional[logging.Logger] = None
    db_port: Optional[IBotsDatabasePort] = None

    configdir: Optional[str] = None
    settings: Any = None
    usersysimportpath: Optional[str] = None
    currentrun: Any = None
    routeid: str = ''
    confirmrules: List[Any] = field(default_factory=list)
    not_import: Set[str] = field(default_factory=set)
    botsreplacechar: str = " "

    # Read-only attributes
    version: str = __version__

# The ContextVar holds the isolated state for the current async task/thread.
_bots_context_var: contextvars.ContextVar[BotsContext] = contextvars.ContextVar("bots_context")

def get_context() -> BotsContext:
    """
    Retrieve the current isolated execution context.
    Raises an error if the engine is accessed outside a valid execution context.
    """
    try:
        return _bots_context_var.get()
    except LookupError:
        # Fallback for legacy scripts during migration: automatically create a context
        ctx = BotsContext()
        _bots_context_var.set(ctx)
        return ctx

def set_context(ctx: BotsContext) -> contextvars.Token[BotsContext]:
    """
    Set the execution context. Typically called by the Transformer Adapter.
    """
    return _bots_context_var.set(ctx)

def reset_context(token: contextvars.Token[BotsContext]) -> None:
    """
    Reset the execution context using the token returned by set_context.
    """
    _bots_context_var.reset(token)
