import pytest
from identity_worker.adapters.outbound.identity_provider.dummy_identity_provider import (
    DummyIdentityProviderPort,
)
from identity_worker.bootstrap.config import Settings, get_settings
from identity_worker.bootstrap.container import UserRoleAssignedPayload, WorkerContainer
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio


async def test_dummy_identity_provider_returns_unique_user_ids():
    provider = DummyIdentityProviderPort()

    first_id = await provider.create_user("org", "a@example.com", "A", "User")
    second_id = await provider.create_user("org", "b@example.com", "B", "User")

    assert first_id != second_id


async def test_user_role_payload_accepts_missing_idp_mapping():
    payload = UserRoleAssignedPayload.model_validate(
        {"user_id": "user-1", "tenant_id": "tenant-1", "role_name": "admin"}
    )

    assert payload.idp_user_id is None


async def test_zitadel_default_password_is_required(monkeypatch):
    monkeypatch.delenv("ZITADEL_DEFAULT_USER_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="zitadel_default_user_password"):
        Settings(_env_file=None)


async def test_worker_container_requires_database_url(monkeypatch):

    bad_settings = Settings(
        database_url="",
        zitadel_default_user_password="not-for-production",  # noqa: S106 - test credential
    )
    with pytest.raises(ValueError, match="database_url"):
        WorkerContainer(settings=bad_settings)

    get_settings.cache_clear()
