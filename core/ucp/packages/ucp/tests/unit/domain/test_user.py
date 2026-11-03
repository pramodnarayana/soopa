from datetime import datetime

from identity.domain.exceptions import IdentityErrorCode
from identity.domain.user import User
from seedwork.utils import generate_id

from ucp.domain.constants import UcpEventType
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix


def test_user_mark_deleted_success() -> None:
    user = User.create(
        id=generate_id(DomainIdPrefix.USER),
        idp_user_id="zitadel-user-1",
        email="test@example.com",
        name="Test User",
    ).unwrap()
    assert user.deleted_at is None

    res = user.mark_deleted()

    assert res.is_ok
    assert user.deleted_at is not None
    assert isinstance(user.deleted_at, datetime)
    assert len(user.domain_events) == 1
    event = user.domain_events[0]
    assert event.event_name == UcpEventType.USER_DELETED.value


def test_user_mark_deleted_already_deleted() -> None:
    user = User.create(
        id=generate_id(DomainIdPrefix.USER),
        idp_user_id="zitadel-user-1",
        email="test@example.com",
        name="Test User",
    ).unwrap()
    assert user.mark_deleted().is_ok

    second = user.mark_deleted()
    assert second.is_err
    assert second.unwrap_err().code == IdentityErrorCode.USER_ALREADY_DELETED
