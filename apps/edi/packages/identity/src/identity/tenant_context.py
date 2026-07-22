"""
Tenant Context Management for Hybrid Tenancy.
Uses Python contextvars to track the active tenant ID across async boundaries.
"""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

# The global context variable storing the active tenant ID.
# It is thread-safe and async-safe.
_tenant_id: ContextVar[int | None] = ContextVar("tenant_id", default=None)


def get_tenant_id() -> int | None:
    """
    Retrieves the current tenant ID from the context.
    Returns None if no tenant context is active (e.g., in a global background job).
    """
    return _tenant_id.get()


def set_tenant_id(tenant_id: int) -> None:
    """
    Sets the active tenant ID for the current context.
    Typically called by an Authentication Middleware in FastAPI.
    """
    _tenant_id.set(tenant_id)


@contextmanager
def tenant_context(tenant_id: int) -> Generator[None, None, None]:
    """
    Context manager to temporarily execute code within a specific tenant context.
    Useful for background workers or CLI scripts.

    Example:
        with tenant_context(1):
            # Database queries here will automatically append WHERE tenant_id = 1
            pass
    """
    token = _tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _tenant_id.reset(token)
