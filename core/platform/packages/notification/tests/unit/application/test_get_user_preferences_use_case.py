import pytest

from notification.application.get_user_preferences_use_case import (
    GetUserPreferencesUseCase,
)
from notification.domain.models import Channel, UserNotificationPreference
from notification.testing.fakes import FakeNotificationUow, FakeUserPrefRepo


@pytest.mark.asyncio
async def test_get_user_preferences_use_case():
    fake_pref_repo = FakeUserPrefRepo()
    fake_uow = FakeNotificationUow(
        user_preference_repo=fake_pref_repo,
        template_repo=None,
        record_repo=None,
        route_repo=None,
        outbox_repo=None,
    )
    use_case = GetUserPreferencesUseCase(uow=fake_uow)

    tenant_id = "ten_123"
    user_id = "usr_456"

    # 1. Initially empty
    result = await use_case.execute(tenant_id, user_id)
    assert result == []

    # 2. Add some preferences
    pref1 = UserNotificationPreference(
        id="pref_1",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="test.event",
        channel=Channel.EMAIL,
        is_enabled=True,
    )
    pref2 = UserNotificationPreference(
        id="pref_2",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="test.event",
        channel=Channel.IN_APP,
        is_enabled=True,
    )
    # Different user
    pref3 = UserNotificationPreference(
        id="pref_3",
        tenant_id=tenant_id,
        user_id="usr_999",
        event_type="test.event",
        channel=Channel.EMAIL,
        is_enabled=True,
    )
    await fake_pref_repo.save_preference(pref1)
    await fake_pref_repo.save_preference(pref2)
    await fake_pref_repo.save_preference(pref3)

    # 3. Fetch again
    result = await use_case.execute(tenant_id, user_id)
    assert len(result) == 2
    assert pref1 in result
    assert pref2 in result
    assert pref3 not in result
