class DatabaseError(Exception):
    """Base exception for all database operations."""


class DuplicateEntityError(DatabaseError):
    """
    Raised when an infrastructure constraint (e.g. unique constraint) is violated.
    This is a pure exception that can be caught by bounded contexts without
    exposing the underlying database driver specifics.
    """

    def __init__(self, message: str, constraint_name: str | None = None):
        super().__init__(message)
        self.constraint_name = constraint_name


class ForeignKeyViolationError(DatabaseError):
    """
    Raised when an infrastructure constraint (e.g. foreign key constraint) is violated.
    This is a pure exception that can be caught by bounded contexts without
    exposing the underlying database driver specifics.
    """

    def __init__(self, message: str, constraint_name: str | None = None):
        super().__init__(message)
        self.constraint_name = constraint_name
