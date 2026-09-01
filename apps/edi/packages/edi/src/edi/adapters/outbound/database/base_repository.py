from database.repository import BaseSqlAlchemyRepository as PlatformBaseSqlAlchemyRepository
from database.types import GlobalSession, TenantSession


class GlobalSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Control Plane repositories.
    Strictly enforces that the injected session is a GlobalSession.
    """

    session: GlobalSession

    def __init__(self, session: GlobalSession) -> None:
        info = getattr(session, "info", {})
        if isinstance(info, dict) and info.get("session_type") != "global":
            raise ValueError(
                f"Expected a GlobalSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
        self.session = session


class TenantSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Data Plane / Shard repositories.
    Strictly enforces that the injected session is a TenantSession.
    """

    session: TenantSession

    def __init__(self, session: TenantSession) -> None:
        info = getattr(session, "info", {})
        if isinstance(info, dict) and info.get("session_type") != "tenant":
            raise ValueError(
                f"Expected a TenantSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
