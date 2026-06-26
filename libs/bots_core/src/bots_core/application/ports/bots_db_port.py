from abc import ABC, abstractmethod
from typing import Any, Iterable

class IBotsDatabasePort(ABC):
    """
    Port for the BOTS engine to interact with the database.
    This interface completely isolates the BOTS engine from the underlying
    database framework (e.g. Django, SQLAlchemy).
    """

    @abstractmethod
    def query(self, querystring: str, *args: Any) -> Iterable[dict[str, Any]]:
        """
        Execute a raw SQL query and return an iterable of dictionary rows.

        Args:
            querystring: The SQL query string to execute.
            *args: Positional arguments to bind to the query.

        Returns:
            An iterable of dictionaries, where keys are column names.
        """
        pass

    @abstractmethod
    def changeq(self, querystring: str, *args: Any) -> int:
        """
        Execute a raw SQL command that mutates data (INSERT/UPDATE/DELETE).

        Args:
            querystring: The SQL command string to execute.
            *args: Positional arguments to bind to the command.

        Returns:
            The number of rows affected.
        """
        pass

    @abstractmethod
    def insertta(self, querystring: str, *args: Any) -> int:
        """
        Insert a row into the `ta` table and return the new row's auto-increment ID.

        Args:
            querystring: The SQL insert command.
            *args: Positional arguments to bind.

        Returns:
            The ID of the inserted row.
        """
        pass

    @abstractmethod
    def unique(self, domain: str, updatewith: int | None = None) -> int:
        """
        Generate or update a unique sequence number for a given domain using the database.

        Args:
            domain: The sequence domain name.
            updatewith: If provided, explicitly sets the sequence counter to this value.

        Returns:
            The generated or updated sequence number.
        """
        pass
