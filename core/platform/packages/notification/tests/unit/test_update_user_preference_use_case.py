import uuid

import pytest

from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.domain.models import Channel, UserNotificationPreference
from notification.testing.fakes import FakeNotificationUow, FakeUserPrefRepo


@pytest.fixture
def fake_repo():
    return FakeUserPrefRepo()


@pytest.fixture
def use_case(fake_repo):
    uow = FakeNotificationUow(
        user_preference_repo=fake_repo,
        template_repo=None,
        record_repo=None,
        route_repo=None,
        outbox_repo=None,
    )
    return UpdateUserPreferenceUseCase(uow=uow)


@pytest.mark.asyncio
async def test_execute_upserts_and_returns(
    use_case: UpdateUserPreferenceUseCase, fake_repo: FakeUserPrefRepo
):
    # Arrange
    tenant_id = f"ten_123-{uuid.uuid4().hex[:8]}"
    user_id = "usr_123"
    event_type = "invoice.payment_failed"
    channel = "EMAIL"
    is_enabled = False

    initial_pref = UserNotificationPreference(
        id="notif_pref_test",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=Channel(channel),
        is_enabled=True,  # Initially true
    )
    fake_repo.prefs[(tenant_id, user_id, event_type, Channel.EMAIL.value)] = initial_pref

    # Act
    result = await use_case.execute(tenant_id, user_id, event_type, channel, False)

    # Assert
    saved_pref = fake_repo.prefs[(tenant_id, user_id, event_type, Channel.EMAIL.value)]
    assert saved_pref.tenant_id == tenant_id
    assert saved_pref.user_id == user_id
    assert saved_pref.event_type == event_type
    assert saved_pref.channel == Channel.EMAIL
    assert saved_pref.is_enabled == is_enabled

    assert not result.is_enabled
