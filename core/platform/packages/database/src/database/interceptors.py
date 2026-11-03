from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sqlalchemy.exc import DBAPIError, IntegrityError

from database.exceptions import DatabaseError, DuplicateEntityError, ForeignKeyViolationError


class PostgresErrorCodes(StrEnum):
    """
    Standard PostgreSQL Error Codes (SQLSTATE).
    Reference: https://www.postgresql.org/docs/current/errcodes-appendix.html
    """

    UNIQUE_VIOLATION = "23505"
    FOREIGN_KEY_VIOLATION = "23503"
    INVALID_SCHEMA_NAME = "3F000"
    UNDEFINED_TABLE = "42P01"


@runtime_checkable
class _PgCodeCarrier(Protocol):
    @property
    def pgcode(self) -> str | None: ...


@runtime_checkable
class _SqlStateCarrier(Protocol):
    @property
    def sqlstate(self) -> str | None: ...


@runtime_checkable
class _ConstraintNameCarrier(Protocol):
    @property
    def constraint_name(self) -> str | None: ...


def _extract_code_from_carrier(carrier: object) -> str | None:
    if isinstance(carrier, _PgCodeCarrier) and carrier.pgcode:
        return carrier.pgcode
    if isinstance(carrier, _SqlStateCarrier) and carrier.sqlstate:
        return carrier.sqlstate
    return None


def extract_postgres_error_metadata(exc: BaseException) -> tuple[str | None, str | None]:
    """Extracts (sqlstate_code, constraint_name) from a SQLAlchemy/DBAPI exception chain."""
    code: str | None = None
    constraint_name: str | None = None

    orig: object = exc.orig if isinstance(exc, DBAPIError) else exc
    if orig is not None:
        code = _extract_code_from_carrier(orig)
        if isinstance(orig, _ConstraintNameCarrier):
            constraint_name = orig.constraint_name

        orig_cause = orig.__cause__ if isinstance(orig, BaseException) else None
        if orig_cause is not None:
            if not code:
                code = _extract_code_from_carrier(orig_cause)
            if not constraint_name and isinstance(orig_cause, _ConstraintNameCarrier):
                constraint_name = orig_cause.constraint_name

    return code, constraint_name


@contextlib.asynccontextmanager
async def intercept_db_errors() -> AsyncGenerator[None, None]:
    """
    Context manager that intercepts raw SQLAlchemy database errors and translates them
    into the standard monorepo Platform Infrastructure Exceptions.
    """
    try:
        yield
    except IntegrityError as exc:
        code, constraint_name = extract_postgres_error_metadata(exc)

        error_map = {
            PostgresErrorCodes.UNIQUE_VIOLATION.value: (
                DuplicateEntityError,
                "A unique constraint was violated.",
            ),
            PostgresErrorCodes.FOREIGN_KEY_VIOLATION.value: (
                ForeignKeyViolationError,
                "A foreign key constraint was violated.",
            ),
        }

        if code in error_map:
            exception_cls, default_message = error_map[code]
            raise exception_cls(
                message=default_message,
                constraint_name=constraint_name,
            ) from exc

        raise DatabaseError("Database integrity error occurred.") from exc
