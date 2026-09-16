import pytest
from identity_worker.bootstrap.container import UserRoleAssignedPayload, WorkerContainer
from identity_worker.config.settings import AppSettings, get_settings
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio


async def test_user_role_payload_accepts_missing_idp_mapping():
    payload = UserRoleAssignedPayload.model_validate(
        {"user_id": "user-1", "tenant_id": "tenant-1", "role_name": "admin"}
    )

    assert payload.idp_user_id is None


async def test_zitadel_default_password_is_required(monkeypatch):
    monkeypatch.delenv("ZITADEL_DEFAULT_USER_PASSWORD", raising=False)

    with pytest.raises(ValidationError, match="ZITADEL_DEFAULT_USER_PASSWORD"):
        AppSettings(_env_file=None)


async def test_worker_container_requires_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")

    bad_settings = AppSettings(_env_file=None, zitadel_default_user_password="not-for-production")
    with pytest.raises(ValueError, match="database_url"):
        WorkerContainer(settings=bad_settings)

    get_settings.cache_clear()
