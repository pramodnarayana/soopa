from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from platform_orm.clients.identity import IdentityClient

from api.ports.api_token_repository import ApiTokenRepositoryPort


class SqlAlchemyApiTokenRepository(ApiTokenRepositoryPort):
    """Repository for managing platform API tokens in the global (control plane) DB."""

    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)  # type: ignore

    async def get_tenant_id_by_credentials(self, client_id: str, secret_hash: str) -> str | None:
        """
        Uses the Platform Identity SDK to verify the token without leaking Domain Models.
        """
        identity_client = IdentityClient(self.session)  # type: ignore
        return await identity_client.get_tenant_id_by_credentials(client_id, secret_hash)
