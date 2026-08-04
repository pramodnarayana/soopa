from sqlalchemy.orm import DeclarativeBase, registry

GlobalRegistry = registry()


class UcpBase(DeclarativeBase):
    """
    Base class for models residing in the UCP boundary (e.g., identity, routing).
    Uses the 'ucp' schema in the Global Control Plane DB.
    """

    registry = GlobalRegistry
    __table_args__ = {"schema": "ucp"}


class EdiGlobalBase(DeclarativeBase):
    """
    Base class for models residing in the EDI boundary (e.g., EDI configurations).
    Uses the 'edi' schema in the Global Control Plane DB.
    """

    registry = GlobalRegistry
    __table_args__ = {"schema": "edi"}
