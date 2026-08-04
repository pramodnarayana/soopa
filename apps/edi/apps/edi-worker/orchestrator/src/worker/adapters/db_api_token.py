import contextlib

from database.connection import DatabaseRouter
from sqlalchemy.dialects.postgresql import insert
from ucp_models.identity import ApiToken

from worker.ports.api_token import ApiTokenPort


class SqlAlchemyApiTokenAdapter(ApiTokenPort):
    def __init__(self, db_router: DatabaseRouter):
        self.db_router = db_router

    async def create_api_token(
        self, tenant_id: str, name: str, client_id: str, key_hash: str
    ) -> None:
        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = (
                insert(ApiToken)
                .values(
                    tenant_id=tenant_id,
                    name=name,
                    client_id=client_id,
                    client_secret=key_hash,
                    active=True,
                )
                .on_conflict_do_nothing(index_elements=["client_id"])
            )

            await global_session.execute(stmt)
            await global_session.commit()
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()
