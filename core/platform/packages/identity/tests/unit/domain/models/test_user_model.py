import pytest

from identity.domain.models.user import User


def test_user_create_and_properties():
    user = User.create(id="usr_123", idp_user_id=None, email="test@test.com", name="Test User")
    assert user.id == "usr_123"
    assert user.email == "test@test.com"
    assert user.name == "Test User"
    assert user.status == "active"
    assert user.idp_user_id is None


def test_user_set_idp_user_id():
    user = User.create(id="usr_123", idp_user_id=None, email="test@test.com", name="Test")
    user.set_idp_user_id("idp_123")
    assert user.idp_user_id == "idp_123"

    with pytest.raises(ValueError):
        user.set_idp_user_id("idp_456")


def test_user_status_changes():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.deactivate()
    assert user.status == "inactive"

    # deactivating again does nothing
    user.deactivate()
    assert user.status == "inactive"

    user.activate()
    assert user.status == "active"

    # activating again does nothing
    user.activate()
    assert user.status == "active"


def test_user_change_status():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.change_status("deactivate", "tenant_123")
    assert user.status == "inactive"

    user.change_status("activate", "tenant_123")
    assert user.status == "active"

    with pytest.raises(ValueError):
        user.change_status("invalid_action", "tenant_123")


def test_user_update_profile():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.update_profile("First", "Last", "tenant_123", "role_123")
    assert user.name == "First Last"


def test_user_mark_deleted():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.mark_deleted()
    assert user.deleted_at is not None

    with pytest.raises(ValueError):
        user.mark_deleted()


def test_user_remove_membership():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.remove_membership("tenant_123")
    assert len(user.domain_events) == 1
    assert user.domain_events[0].event_name == "UserMembershipRemoved"


def test_user_assign_role():
    user = User.create(id="usr_123", idp_user_id="idp_123", email="test@test.com", name="Test")
    user.assign_role("role_123", "Role", "tenant_123")
    assert len(user.domain_events) == 1
    assert user.domain_events[0].event_name == "user_role_assigned"
