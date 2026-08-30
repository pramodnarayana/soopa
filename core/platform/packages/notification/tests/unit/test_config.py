from notification.config import NotificationEngineSettings


def test_notification_engine_settings_defaults():
    settings = NotificationEngineSettings()
    assert settings.max_template_size_chars == 10_000
    assert settings.max_payload_size_chars == 50_000
    assert settings.render_timeout_seconds == 2.0


def test_notification_engine_settings_custom():
    settings = NotificationEngineSettings(
        max_template_size_chars=100,
        max_payload_size_chars=200,
        render_timeout_seconds=5.5,
    )
    assert settings.max_template_size_chars == 100
    assert settings.max_payload_size_chars == 200
    assert settings.render_timeout_seconds == 5.5
