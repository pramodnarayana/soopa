import pytest
from database.utils import normalize_to_asyncpg

from notification_email_worker.config.settings import get_settings


def test_settings_load_nested_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://global")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("SQS_EMAIL_CHANNEL_QUEUE_URL", "http://sqs.email")

    try:
        get_settings.cache_clear()
        settings = get_settings()

        assert settings.database.global_url == normalize_to_asyncpg("postgres://global")
        assert settings.aws.resolved_region == "us-west-2"
        assert settings.sqs.email_channel_queue_url == "http://sqs.email"
    finally:
        get_settings.cache_clear()
