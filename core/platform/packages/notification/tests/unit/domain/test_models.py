from notification.domain.models import Channel, NotificationDispatch


def test_notification_dispatch_uses_legacy_target_user_id() -> None:
    dispatch = NotificationDispatch.create(
        tenant_id="ten_1",
        channel=Channel.IN_APP,
        subject="Subject",
        body="Body",
        data={"target_user_id": "usr_1"},
        idempotency_key="evt_1",
    )

    assert dispatch.target_user_id == "usr_1"
    assert len(dispatch.domain_events) == 1
    assert dispatch.domain_events[0].id == "evt_1"
    assert dispatch.domain_events[0].idempotency_key == "evt_1"


def test_notification_dispatch_prefers_user_id_over_legacy_target_user_id() -> None:
    dispatch = NotificationDispatch.create(
        tenant_id="ten_1",
        channel=Channel.IN_APP,
        subject="Subject",
        body="Body",
        data={"user_id": "usr_new", "target_user_id": "usr_legacy"},
        idempotency_key="evt_1",
    )

    assert dispatch.target_user_id == "usr_new"
