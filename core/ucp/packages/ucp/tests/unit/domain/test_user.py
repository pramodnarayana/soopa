from datetime import datetime

import pytest
from identity.domain.constants import IdentityIdPrefix
from identity.domain.models.user import User
from seedwork.utils import generate_id


def test_user_mark_deleted_success() -> None:
    user = User.create(
        id=generate_id(IdentityIdPrefix.USER),
        idp_user_id="zitadel-user-1",
        email="test@example.com",
        name="Test User",
    )
    assert user.deleted_at is None

    user.mark_deleted()

    assert user.deleted_at is not None
    assert isinstance(user.deleted_at, datetime)
    assert len(user.domain_events) == 1
    event = user.domain_events[0]
    assert event.event_name == "UserDeleted"


def test_user_mark_deleted_already_deleted() -> None:
    user = User.create(
        id=generate_id(IdentityIdPrefix.USER),
        idp_user_id="zitadel-user-1",
        email="test@example.com",
        name="Test User",
    )
    user.mark_deleted()

    with pytest.raises(ValueError, match="already been deleted"):
        user.mark_deleted()
