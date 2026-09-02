import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, Protocol, TypeVar, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from database.interceptors import intercept_db_errors

P = ParamSpec("P")
R = TypeVar("R")


@runtime_checkable
class HasDomainEvents(Protocol):
    """
    Structural protocol satisfied by any AggregateRoot that exposes
    `domain_events` and `clear_domain_events()`. Avoids importing seedwork
    directly into the platform database package.
    """

    @property
    def domain_events(self) -> list[Any]: ...

    def clear_domain_events(self) -> None: ...


def db_error_interceptor(
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """
    Decorator that applies the intercept_db_errors context manager to a repository method.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        async with intercept_db_errors():
            return await func(*args, **kwargs)

    return wrapper


class BaseSqlAlchemyRepository:
    """
    Base Repository providing common SQLAlchemy operations wrapped with
    centralized Platform exception translation.
    """

    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @db_error_interceptor
    async def flush(self) -> None:
        """
        Flush the current session, automatically translating any IntegrityError
        (like Unique Constraint violations) into Platform Infrastructure Errors.
        """
        await self.session.flush()
