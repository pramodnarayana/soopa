from collections.abc import Iterable
from typing import Any

from bots_core.application.ports.bots_db_port import IBotsDatabasePort
from sqlalchemy.orm import Session


class SqlAlchemyBotsDatabaseAdapter(IBotsDatabasePort):
    """
    Adapter that implements IBotsDatabasePort using a SQLAlchemy Session.
    This fulfills the database requirements of the BOTS engine.
    """

    def __init__(self, session: Session):
        self.session = session

    def query(self, querystring: str, *args: Any) -> Iterable[dict[str, Any]]:
        """
        Execute a raw SQL query using SQLAlchemy.
        Converts the %s or %(name)s format used by DBAPI to SQLAlchemy text parameters,
        but since the engine passes args, we execute raw text.
        """
        # SQLAlchemy connection.execute handles raw strings and args differently depending on the driver.
        # But text() with bound params is safer.
        # For a naive DBAPI-like execute, we can use the underlying connection cursor.
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        cursor.execute(querystring, *args)

        # dictfetchall logic
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        cursor.close()
        return results

    def changeq(self, querystring: str, *args: Any) -> int:
        """
        Execute an INSERT/UPDATE/DELETE statement.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        cursor.execute(querystring, *args)
        rowcount = cursor.rowcount
        self.session.commit()
        cursor.close()
        return rowcount

    def insertta(self, querystring: str, *args: Any) -> int:
        """
        Insert into ta and return last insert id.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        cursor.execute(querystring, *args)
        newidta = cursor.lastrowid if hasattr(cursor, "lastrowid") else 0
        if not newidta:
            # PostgreSQL fallback if lastrowid is missing
            cursor.execute("SELECT lastval() as idta")
            row = cursor.fetchone()
            if not row:
                raise TypeError("No results")
            columns = [col[0] for col in cursor.description]
            row_dict = dict(zip(columns, row, strict=False))
            newidta = int(row_dict["idta"])

        self.session.commit()
        cursor.close()
        return int(newidta)

    def unique(self, domain: str, updatewith: int | None = None) -> int:
        """
        Generate or update unique sequence number for domain.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        try:
            cursor.execute("SELECT nummer FROM uniek WHERE domein=%(domein)s", {"domein": domain})
            row = cursor.fetchone()
            if not row:
                raise TypeError("No results")
            columns = [col[0] for col in cursor.description]
            row_dict = dict(zip(columns, row, strict=False))
            nummer = row_dict["nummer"]

            if updatewith is None:
                nummer += 1
                updatewith = nummer

            cursor.execute(
                "UPDATE uniek SET nummer=%(nummer)s WHERE domein=%(domein)s",
                {"domein": domain, "nummer": updatewith},
            )
        except TypeError:
            # Insert if it does not exist
            cursor.execute(
                "INSERT INTO uniek (domein,nummer) VALUES (%(domein)s,1)", {"domein": domain}
            )
            nummer = 1

        self.session.commit()
        cursor.close()
        return nummer
