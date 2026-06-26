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
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        try:
            cursor.execute(querystring, *args)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def changeq(self, querystring: str, *args: Any) -> int:
        """
        Execute an INSERT/UPDATE/DELETE statement.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        try:
            cursor.execute(querystring, *args)
            rowcount = cursor.rowcount
            self.session.commit()
            return rowcount
        except Exception:
            self.session.rollback()
            raise
        finally:
            cursor.close()

    def insertta(self, querystring: str, *args: Any) -> int:
        """
        Insert into ta and return last insert id.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        try:
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
            return int(newidta)
        except Exception:
            self.session.rollback()
            raise
        finally:
            cursor.close()

    def unique(self, domain: str, updatewith: int | None = None) -> int:
        """
        Generate or update unique sequence number for domain.
        Uses SELECT ... FOR UPDATE to prevent race conditions across workers.
        """
        connection = self.session.connection()
        cursor = connection.connection.cursor()
        try:
            cursor.execute(
                "SELECT nummer FROM uniek WHERE domein=%(domein)s FOR UPDATE", {"domein": domain}
            )
            row = cursor.fetchone()

            if not row:
                nummer = 1 if updatewith is None else updatewith
                cursor.execute(
                    "INSERT INTO uniek (domein,nummer) VALUES (%(domein)s,%(nummer)s)",
                    {"domein": domain, "nummer": nummer},
                )
            else:
                columns = [col[0] for col in cursor.description]
                row_dict = dict(zip(columns, row, strict=False))
                nummer = int(row_dict["nummer"])

                if updatewith is None:
                    nummer += 1
                else:
                    nummer = updatewith

                cursor.execute(
                    "UPDATE uniek SET nummer=%(nummer)s WHERE domein=%(domein)s",
                    {"domein": domain, "nummer": nummer},
                )

            self.session.commit()
            return nummer
        except Exception:
            self.session.rollback()
            raise
        finally:
            cursor.close()
