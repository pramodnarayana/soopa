import secrets
from datetime import UTC, datetime, timedelta

import pytest
from database.models.identity import Tenant as OrmTenant
from seedwork import generate_id, generate_random_hex
from sqlalchemy.dialects.postgresql import insert as pg_insert

from identity.adapters.outbound.database.api_token_repository import SqlAlchemyApiTokenRepository
from identity.domain.api_token import ApiToken
from identity.domain.constants import IdentityIdPrefix as DomainIdPrefix
from identity.domain.identity_context import M2M_CLIENT_ID_PREFIX

pytestmark = pytest.mark.integration


@pytest.fixture
def dummy_tenant_data() -> dict[str, object]:
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    return {
        "id": tenant_id,
        "name": f"Api Token Test Tenant {generate_random_hex(6)}",
        "slug": f"api-token-tenant-{generate_random_hex(6)}",
        "idp_tenant_id": f"zitadel_org_{generate_random_hex(8)}",
        "status": "active",
        "created_at": now_naive,
        "updated_at": now_naive,
    }


@pytest.fixture
def dummy_token_data(dummy_tenant_data: dict[str, object]) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": generate_id(DomainIdPrefix.TOKEN.value),
        "tenant_id": str(dummy_tenant_data["id"]),
        "name": "Test Token",
        "client_id": f"{M2M_CLIENT_ID_PREFIX}{secrets.token_hex(16)}",
        "secret_hash": "hash_xyz",
        "active": True,
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_api_token_repository_lifecycle(
    db_session_factory,
    dummy_tenant_data: dict[str, object],
    dummy_token_data: dict[str, object],
) -> None:
    async with db_session_factory() as db_session, db_session.begin_nested():
        repo = SqlAlchemyApiTokenRepository(db_session)

        # Insert Tenant First
        stmt = (
            pg_insert(OrmTenant)
            .values([dummy_tenant_data])
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db_session.execute(stmt)

        # 1. Save New Token
        domain_model = ApiToken(
            id=str(dummy_token_data["id"]),
            tenant_id=str(dummy_token_data["tenant_id"]),
            name=str(dummy_token_data["name"]),
            client_id=str(dummy_token_data["client_id"]),
            secret_hash=str(dummy_token_data["secret_hash"]),
            last_used_at=None,
            expires_at=None,
            active=bool(dummy_token_data["active"]),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        created_token = await repo.save(domain_model)
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

        # 4b. Expired token is excluded by get_by_client_id
        expired_domain = ApiToken(
            id=f"{created_token.id}_expired",
            tenant_id=created_token.tenant_id,
            name="Expired Token",
            client_id=f"{created_token.client_id}_expired",
            secret_hash=created_token.secret_hash,
            last_used_at=None,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            active=True,
            created_at=datetime.now(UTC) - timedelta(hours=1),
            updated_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await repo.save(expired_domain)
        assert await repo.get_by_client_id(expired_domain.client_id) is None

        # 5. Update Token via Aggregate Behavior + save()
        assert created_token.rename("Updated Token Name").is_ok
        updated_token = await repo.save(created_token)
        assert updated_token.name == "Updated Token Name"

        # 6. Delete Token
        deleted = await repo.delete(created_token.id, created_token.tenant_id)
        assert deleted is True

        # Verify deleted
        not_found = await repo.get_by_id(created_token.id, created_token.tenant_id)
        assert not_found is None
