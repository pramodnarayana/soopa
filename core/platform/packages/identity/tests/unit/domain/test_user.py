from seedwork.utils import generate_id

from identity.domain.constants import (
    IdentityEventType,
    IdentityIdPrefix,
    UserStatus,
    UserStatusAction,
)
from identity.domain.events import UserCreatedEvent, UserUpdatedEvent
from identity.domain.exceptions import IdentityErrorCode
from identity.domain.user import User


def test_user_create_and_validation() -> None:
    user_id = generate_id(IdentityIdPrefix.USER.value)
    res = User.create(id=user_id, idp_user_id=None, email="  test@test.com  ", name="  Test User  ")
    assert res.is_ok
    user = res.unwrap()
    assert user.id == user_id
    assert user.email == "test@test.com"
    assert user.name == "Test User"
    assert user.status == UserStatus.ACTIVE
    assert user.idp_user_id is None

    bad_email = User.create(id=user_id, idp_user_id=None, email="not-an-email", name="Test User")
    assert bad_email.is_err
    assert bad_email.unwrap_err().code == IdentityErrorCode.VALIDATION_FAILED

    bad_name = User.create(id=user_id, idp_user_id=None, email="test@test.com", name="   ")
    assert bad_name.is_err
    assert bad_name.unwrap_err().code == IdentityErrorCode.VALIDATION_FAILED


def test_user_set_idp_user_id() -> None:
    user = User.create(email="test@test.com", name="Test").unwrap()
    res = user.set_idp_user_id("idp_123")
    assert res.is_ok
    assert user.idp_user_id == "idp_123"

    # Idempotent re-set to the same ID succeeds
    same_res = user.set_idp_user_id("idp_123")
    assert same_res.is_ok

    err_res = user.set_idp_user_id("idp_456")
    assert err_res.is_err
    assert err_res.unwrap_err().code == IdentityErrorCode.IDP_MAPPING_CONFLICT


def test_user_status_changes() -> None:
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    user.deactivate()
    assert user.status == UserStatus.INACTIVE

    user.deactivate()
    assert user.status == UserStatus.INACTIVE

    user.activate()
    assert user.status == UserStatus.ACTIVE

    user.activate()
    assert user.status == UserStatus.ACTIVE


def test_user_change_status() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    res_deact = user.change_status(UserStatusAction.DEACTIVATE, tenant_id)
    assert res_deact.is_ok
    assert user.status == UserStatus.INACTIVE

    res_act = user.change_status(UserStatusAction.ACTIVATE, tenant_id)
    assert res_act.is_ok
    assert user.status == UserStatus.ACTIVE


def test_user_update_profile() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    role_id = generate_id(IdentityIdPrefix.ROLE.value)
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    upd_ok = user.update_profile("First", "Last", tenant_id, role_id)
    assert upd_ok.is_ok
    assert user.name == "First Last"
    assert isinstance(user.domain_events[-1], UserUpdatedEvent)

    upd_err = user.update_profile("  ", "  ", tenant_id, role_id)
    assert upd_err.is_err
    assert upd_err.unwrap_err().code == IdentityErrorCode.VALIDATION_FAILED


def test_user_mark_deleted() -> None:
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    res = user.mark_deleted()
    assert res.is_ok
    assert user.deleted_at is not None

    err_res = user.mark_deleted()
    assert err_res.is_err
    assert err_res.unwrap_err().code == IdentityErrorCode.USER_ALREADY_DELETED


def test_user_record_invitation() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    user = User.create(idp_user_id=None, email="invitee@test.com", name="Jane Doe").unwrap()
    user.record_invitation(
        tenant_id=tenant_id,
        first_name="Jane",
        last_name="Doe",
        role="admin",
    )
    assert len(user.domain_events) == 1
    assert isinstance(user.domain_events[0], UserCreatedEvent)
    assert user.domain_events[0].event_name == IdentityEventType.USER_INVITED.value


def test_user_remove_membership() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    user.remove_membership(tenant_id)
    assert len(user.domain_events) == 1
    assert user.domain_events[0].event_name == IdentityEventType.USER_MEMBERSHIP_REMOVED.value


def test_user_assign_role() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    role_id = generate_id(IdentityIdPrefix.ROLE.value)
    user = User.create(idp_user_id="idp_123", email="test@test.com", name="Test").unwrap()
    user.assign_role(role_id, "Role", tenant_id)
    assert len(user.domain_events) == 1
    assert user.domain_events[0].event_name == IdentityEventType.USER_ROLE_ASSIGNED.value
