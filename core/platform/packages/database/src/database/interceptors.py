import contextlib
from collections.abc import AsyncGenerator

from sqlalchemy.exc import IntegrityError

from database.exceptions import DatabaseError, DuplicateEntityError, ForeignKeyViolationError


class PostgresErrorCodes:
    """
    Standard PostgreSQL Error Codes (SQLSTATE).
    Reference: https://www.postgresql.org/docs/current/errcodes-appendix.html
    """

    UNIQUE_VIOLATION = "23505"
    FOREIGN_KEY_VIOLATION = "23503"


@contextlib.asynccontextmanager
async def intercept_db_errors() -> AsyncGenerator[None, None]:
    """
    Context manager that intercepts raw SQLAlchemy database errors and translates them
    into the standard monorepo Platform Infrastructure Exceptions.
    """
    try:
        yield
    except IntegrityError as exc:
        pgcode = None
        sqlstate = None
        constraint_name = None

        # psycopg (asyncpg) exposes pgcode and sqlstate via the orig exception
        if hasattr(exc, "orig"):
            pgcode = getattr(exc.orig, "pgcode", None)
            sqlstate = getattr(exc.orig, "sqlstate", None)
            orig_cause = getattr(exc.orig, "__cause__", None)

            if orig_cause is not None:
                constraint_name = getattr(orig_cause, "constraint_name", None)
                if not pgcode:
                    pgcode = getattr(orig_cause, "pgcode", None)
                if not sqlstate:
                    sqlstate = getattr(orig_cause, "sqlstate", None)
            else:
                constraint_name = getattr(exc.orig, "constraint_name", None)

        code = pgcode or sqlstate
        ERROR_MAP = {
            PostgresErrorCodes.UNIQUE_VIOLATION: (
                DuplicateEntityError,
                "A unique constraint was violated.",
            ),
            PostgresErrorCodes.FOREIGN_KEY_VIOLATION: (
                ForeignKeyViolationError,
                "A foreign key constraint was violated.",
            ),
        }

        if code in ERROR_MAP:
            ExceptionClass, default_message = ERROR_MAP[code]
            raise ExceptionClass(
                message=default_message,
                constraint_name=constraint_name,
            ) from exc

        # Reraise other integrity errors (check constraints, not null, etc) as generic DatabaseError
        raise DatabaseError("Database integrity error occurred.") from exc
