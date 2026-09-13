import os

from database.utils import normalize_to_asyncpg

from scheduler_worker.config.settings import AppSettings


def test_settings_load_nested_env_vars() -> None:
    os.environ["DATABASE_URL"] = "postgres://global"
    os.environ["AWS_REGION"] = "us-west-2"
    os.environ["SQS_DATA_PLANE_JOBS_QUEUE_URL"] = "http://sqs.data"

    settings = AppSettings(_env_file=None)

    # Use the existing function rather than hard-coding the expected transformed URL
    assert settings.database.global_url == normalize_to_asyncpg("postgres://global")
    assert settings.aws.region == "us-west-2"
    assert settings.sqs.data_plane_jobs_queue_url == "http://sqs.data"
