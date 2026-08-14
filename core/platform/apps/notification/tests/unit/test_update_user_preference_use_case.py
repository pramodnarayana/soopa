from unittest.mock import AsyncMock

import pytest

from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.domain.models import Channel, UserNotificationPreference


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def use_case(mock_repo):
    return UpdateUserPreferenceUseCase(repo=mock_repo)


@pytest.mark.asyncio
async def test_execute_upserts_and_returns(
    use_case: UpdateUserPreferenceUseCase, mock_repo: AsyncMock
):
    # Arrange
    tenant_id = "ten_123"
    user_id = "usr_123"
    event_type = "invoice.payment_failed"
    channel = "EMAIL"
    is_enabled = False

    expected_pref = UserNotificationPreference(
        id="notif_pref_test",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=Channel(channel),
        is_enabled=is_enabled,
    )
    mock_repo.get_preference.return_value = expected_pref

    # Act
    result = await use_case.execute(tenant_id, user_id, event_type, channel, is_enabled)

    # Assert
    assert mock_repo.save_preference.call_count == 1

    saved_pref = mock_repo.save_preference.call_args[0][0]
    assert saved_pref.tenant_id == tenant_id
    assert saved_pref.user_id == user_id
    assert saved_pref.event_type == event_type
    assert saved_pref.channel == Channel.EMAIL
    assert saved_pref.is_enabled == is_enabled
    assert saved_pref.id.startswith("notif_pref_")

    assert mock_repo.get_preference.call_count == 1
    assert result == expected_pref
