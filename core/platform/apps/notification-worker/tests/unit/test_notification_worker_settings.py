"""
Regression tests for notification_worker AppSettings nested field factories
and startup PUBSUB_TRANSPORT policy validation.
"""

from collections.abc import Generator

import pytest
from database.utils import normalize_to_asyncpg
from pydantic import ValidationError

from notification_worker.config.settings import AppSettings, get_settings


@pytest.fixture(autouse=True)
def notification_worker_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Inject the minimum required environment variables for AppSettings construction."""
    monkeypatch.setenv("DATABASE_URL", "postgres://global")
    monkeypatch.setenv("PUBSUB_TRANSPORT", "aws")
    monkeypatch.setenv("SQS_NOTIFICATION_QUEUE_URL", "http://sqs.localhost/000/notifications.fifo")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    get_settings.cache_clear()

    try:
        yield
    finally:
        get_settings.cache_clear()


def test_app_settings_database_nested_model_loads_from_env() -> None:
    """PlatformDatabaseSettings.global_url must be loaded from DATABASE_URL env var."""
    settings = get_settings()

    assert settings.database.global_url is not None
    assert settings.database.global_url == normalize_to_asyncpg("postgres://global")
    assert settings.database_url == settings.database.global_url


def test_app_settings_sqs_nested_model_loads_from_env() -> None:
    """SqsSettings.notification_queue_url must load from SQS_NOTIFICATION_QUEUE_URL."""
    settings = get_settings()

    assert settings.sqs.notification_queue_url == "http://sqs.localhost/000/notifications.fifo"
    assert settings.sqs_notification_queue_url == settings.sqs.notification_queue_url
    assert settings.pubsub_transport == "aws"


def test_app_settings_aws_nested_model_loads_from_env() -> None:
    """PlatformAwsSettings.resolved_region must load from AWS_DEFAULT_REGION."""
    settings = get_settings()

    assert settings.aws.resolved_region == "us-east-1"
    assert settings.aws_region == settings.aws.resolved_region


def test_app_settings_rejects_stale_sqs_uri_under_db_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup validation must fail fast when PUBSUB_TRANSPORT=db receives a LocalStack URL."""
    monkeypatch.setenv("PUBSUB_TRANSPORT", "db")
    monkeypatch.setenv(
        "SQS_NOTIFICATION_QUEUE_URL", "http://localhost:4566/000000000000/notifications.fifo"
    )
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="PUBSUB_TRANSPORT='db'"):
        AppSettings()


def test_app_settings_suppresses_aws_endpoint_in_db_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AWS_ENDPOINT_URL must not leak into db:// workers."""
    monkeypatch.setenv("PUBSUB_TRANSPORT", "db")
    monkeypatch.setenv("SQS_NOTIFICATION_QUEUE_URL", "db://notifications.fifo")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    get_settings.cache_clear()

    settings = AppSettings()
    assert settings.pubsub_transport == "db"
    assert settings.aws_endpoint_url is None
