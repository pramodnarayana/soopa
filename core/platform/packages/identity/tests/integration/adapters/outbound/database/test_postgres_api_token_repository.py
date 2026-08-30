import datetime

import pytest
from database.models.identity import Tenant as OrmTenant
from seedwork import generate_id, generate_random_hex
from sqlalchemy.dialects.postgresql import insert as pg_insert

from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.domain.models.api_token import ApiTokenDomainModel

pytestmark = pytest.mark.integration


@pytest.fixture
def dummy_tenant_data():
    tenant_id = generate_id("ten")
    return {
        "id": tenant_id,
        "name": f"Api Token Test Tenant {generate_random_hex(6)}",
        "slug": f"api-token-tenant-{generate_random_hex(6)}",
        "idp_tenant_id": generate_id("idp"),
        "status": "active",
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }


@pytest.fixture
def dummy_token_data(dummy_tenant_data: dict) -> dict:
    return {
        "id": generate_id("tok"),
        "tenant_id": dummy_tenant_data["id"],
        "name": "Test Token",
        "client_id": generate_id("client"),
        "secret_hash": "hash_xyz",
        "active": True,
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }


@pytest.mark.asyncio
async def test_api_token_repository_lifecycle(
    db_session_factory, dummy_tenant_data, dummy_token_data
) -> None:
    async with db_session_factory() as db_session, db_session.begin_nested():
        repo = PostgresApiTokenRepository(db_session)

        # Insert Tenant First
        stmt = (
            pg_insert(OrmTenant)
            .values([dummy_tenant_data])
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db_session.execute(stmt)

        # 1. Create Token
        domain_model = ApiTokenDomainModel(
            id=dummy_token_data["id"],
            tenant_id=dummy_token_data["tenant_id"],
            name=dummy_token_data["name"],
            client_id=dummy_token_data["client_id"],
            secret_hash=dummy_token_data["secret_hash"],
            last_used_at=None,
            expires_at=None,
            active=dummy_token_data["active"],
            created_at=dummy_token_data["created_at"],
            updated_at=dummy_token_data["updated_at"],
        )

        created_token = await repo.create(domain_model)
        assert created_token.id == dummy_token_data["id"]
        assert created_token.name == dummy_token_data["name"]

        # 2. Get by ID
        fetched_token = await repo.get_by_id(created_token.id, created_token.tenant_id)
        assert fetched_token is not None
        assert fetched_token.id == created_token.id

        # 3. Get all by Tenant
        tenant_tokens = await repo.get_all_by_tenant(created_token.tenant_id)
        assert len(tenant_tokens) >= 1
        assert any(t.id == created_token.id for t in tenant_tokens)

        # 4. Get by Client ID
        client_token = await repo.get_by_client_id(created_token.client_id)
        assert client_token is not None
        assert client_token.id == created_token.id

        # 5. Update Token
        updated_token = await repo.update(
            created_token.id, created_token.tenant_id, name="Updated Token Name"
        )
        assert updated_token is not None
        assert updated_token.name == "Updated Token Name"

        # 6. Delete Token
        deleted = await repo.delete(created_token.id, created_token.tenant_id)
        assert deleted is True

        # Verify deleted
        not_found = await repo.get_by_id(created_token.id, created_token.tenant_id)
        assert not_found is None
