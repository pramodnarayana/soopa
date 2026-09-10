"""
Regression tests for notification_worker AppSettings nested field factories.

Verifies that all three nested settings models (PlatformDatabaseSettings,
PlatformAwsSettings, SqsSettings) correctly load their values from os.environ
instead of being validated from empty-dictionary defaults.

This is a regression guard for the cast({}) anti-pattern that caused nested
settings to silently fail to load environment variables during construction.
"""

import pytest

from notification_worker.config.settings import get_settings


@pytest.fixture(autouse=True)
def notification_worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the minimum required environment variables for AppSettings construction."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    monkeypatch.setenv(
        "SQS_PRIORITY_NOTIFICATIONS_QUEUE_URL", "http://sqs.localhost/000/priority.fifo"
    )
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    get_settings.cache_clear()


def test_app_settings_database_nested_model_loads_from_env() -> None:
    """PlatformDatabaseSettings.global_url must be loaded from DATABASE_URL env var."""
    settings = get_settings()

    assert settings.database.global_url is not None
    assert "localhost" in settings.database.global_url
    # Ensure the property proxy works correctly
    assert settings.database_url == settings.database.global_url


def test_app_settings_sqs_nested_model_loads_from_env() -> None:
    """SqsSettings.priority_notifications_queue_url must load from SQS_PRIORITY_NOTIFICATIONS_QUEUE_URL."""
    settings = get_settings()

    assert settings.sqs.priority_notifications_queue_url == "http://sqs.localhost/000/priority.fifo"
    assert (
        settings.sqs_priority_notifications_queue_url
        == settings.sqs.priority_notifications_queue_url
    )


def test_app_settings_aws_nested_model_loads_from_env() -> None:
    """PlatformAwsSettings.resolved_region must load from AWS_DEFAULT_REGION."""
    settings = get_settings()

    assert settings.aws.resolved_region == "us-east-1"
    assert settings.aws_region == settings.aws.resolved_region
