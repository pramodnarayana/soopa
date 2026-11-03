import secrets
from datetime import UTC, datetime, timedelta

from seedwork.domain.aggregate import AggregateRoot
from seedwork.utils import generate_id

from identity.domain.api_token import ApiToken
from identity.domain.constants import IdentityIdPrefix
from identity.domain.exceptions import IdentityErrorCode
from identity.domain.identity_context import M2M_CLIENT_ID_PREFIX


def _client_id() -> str:
    return f"{M2M_CLIENT_ID_PREFIX}{secrets.token_hex(16)}"


def test_api_token_create_and_aggregate_root_inheritance() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    client_id = _client_id()
    res = ApiToken.create(
        tenant_id=tenant_id,
        name="  Production Ingestion Key  ",
        client_id=client_id,
        secret_hash="hash_xyz",
    )
    assert res.is_ok
    token = res.unwrap()
    assert isinstance(token, AggregateRoot)
    assert IdentityIdPrefix.TOKEN.value == token.ID_PREFIX
    assert token.id.startswith("iam_tok_")
    assert token.name == "Production Ingestion Key"
    assert token.active is True
    assert token.last_used_at is None

    empty_res = ApiToken.create(
        tenant_id=tenant_id,
        name="   ",
        client_id=client_id,
        secret_hash="hash_xyz",
    )
    assert empty_res.is_err
    assert empty_res.unwrap_err().code == IdentityErrorCode.INVALID_TOKEN_NAME


def test_api_token_rename_and_revoke_and_activate() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    token = ApiToken.create(
        tenant_id=tenant_id,
        name="Initial Name",
        client_id=_client_id(),
        secret_hash="hash_xyz",
    ).unwrap()

    rename_ok = token.rename("  Updated Name ")
    assert rename_ok.is_ok
    assert token.name == "Updated Name"

    rename_err = token.rename("")
    assert rename_err.is_err
    assert rename_err.unwrap_err().code == IdentityErrorCode.INVALID_TOKEN_NAME

    revoke_ok = token.revoke()
    assert revoke_ok.is_ok
    assert token.active is False

    revoke_again = token.revoke()
    assert revoke_again.is_err
    assert revoke_again.unwrap_err().code == IdentityErrorCode.TOKEN_ALREADY_REVOKED

    activate_ok = token.activate()
    assert activate_ok.is_ok
    assert token.active is True


def test_api_token_record_usage_validates_active_and_expiration() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    token = ApiToken.create(
        tenant_id=tenant_id,
        name="Expiring Token",
        client_id=_client_id(),
        secret_hash="hash_xyz",
        expires_at=now + timedelta(hours=1),
    ).unwrap()

    usage_ok = token.record_usage(used_at=now)
    assert usage_ok.is_ok
    assert token.last_used_at == now

    expired_usage = token.record_usage(used_at=now + timedelta(hours=2))
    assert expired_usage.is_err
    assert expired_usage.unwrap_err().code == IdentityErrorCode.TOKEN_EXPIRED

    token.revoke()
    revoked_usage = token.record_usage(used_at=now)
    assert revoked_usage.is_err
    assert revoked_usage.unwrap_err().code == IdentityErrorCode.TOKEN_INACTIVE


def test_api_token_is_expired_handles_none_boundary_and_naive_timestamps() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    non_expiring = ApiToken.create(
        tenant_id=tenant_id,
        name="Non Expiring",
        client_id=_client_id(),
        secret_hash="hash_xyz",
        expires_at=None,
    ).unwrap()
    assert non_expiring.is_expired(at=now + timedelta(days=3650)) is False

    expiring = ApiToken.create(
        tenant_id=tenant_id,
        name="Expiring",
        client_id=_client_id(),
        secret_hash="hash_xyz",
        expires_at=now + timedelta(minutes=5),
    ).unwrap()
    assert expiring.is_expired(at=now + timedelta(minutes=4, seconds=59)) is False
    assert expiring.is_expired(at=now + timedelta(minutes=5)) is True
    assert expiring.is_expired(at=now + timedelta(minutes=6)) is True

    naive_expiring = ApiToken.create(
        tenant_id=tenant_id,
        name="Naive Expiring",
        client_id=_client_id(),
        secret_hash="hash_xyz",
        expires_at=(now + timedelta(minutes=5)).replace(tzinfo=None),
    ).unwrap()
    assert naive_expiring.is_expired(at=now) is False
    assert naive_expiring.is_expired(at=now + timedelta(minutes=5)) is True
