from __future__ import annotations

from sharding.domain.exceptions import TenantNotFoundError
from sharding.provider import SqlAlchemyTenantShardResolver

from database.router import DatabaseRouterPort

EDI_APP_SLUG = "edi"

__all__ = ["EDI_APP_SLUG", "SqlAlchemyTenantResolver", "TenantNotFoundError"]


class SqlAlchemyTenantResolver(SqlAlchemyTenantShardResolver):
    """
    EDI-specific SqlAlchemyTenantResolver inheriting from the platform TenantShardResolver.
    """

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        ttl_secs: int = 300,
        max_entries: int = 1000,
    ) -> None:
        super().__init__(
            db_router=db_router,
            app_slug=EDI_APP_SLUG,
            ttl_secs=ttl_secs,
            max_entries=max_entries,
        )
        self.db_router = db_router
