import os

from database.utils import normalize_to_asyncpg

from notification_email_worker.config.settings import get_settings


def test_settings_load_nested_env_vars() -> None:
    os.environ["DATABASE_URL"] = "postgres://global"
    os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
    os.environ["SQS_EMAIL_CHANNEL_QUEUE_URL"] = "http://sqs.email"

    try:
        get_settings.cache_clear()
        settings = get_settings()

        assert settings.database.global_url == normalize_to_asyncpg("postgres://global")
        assert settings.aws.resolved_region == "us-west-2"
        assert settings.sqs.email_channel_queue_url == "http://sqs.email"
    finally:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("AWS_DEFAULT_REGION", None)
        os.environ.pop("SQS_EMAIL_CHANNEL_QUEUE_URL", None)
