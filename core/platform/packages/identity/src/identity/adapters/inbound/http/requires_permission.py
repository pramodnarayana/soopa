from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from identity.domain.identity_context import IdentityContext
from identity.domain.permissions import require_permission

P = ParamSpec("P")
R = TypeVar("R")


def requires_permission(permission: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            identity = kwargs.get("identity")
            if not isinstance(identity, IdentityContext):
                msg = "requires_permission expects an IdentityContext keyword argument named 'identity'."
                raise TypeError(msg)
            require_permission(identity, permission)
            return func(*args, **kwargs)

        return wrapper

    return decorator
