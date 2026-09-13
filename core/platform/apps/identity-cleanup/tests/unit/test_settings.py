import os

from identity_cleanup.config.settings import AppSettings


def test_settings_load_nested_env_vars() -> None:
    os.environ["DATABASE_GLOBAL_URL"] = "postgres://global"
    os.environ["AWS_REGION"] = "us-west-2"
    os.environ["SQS_DATA_PLANE_JOBS_QUEUE_URL"] = "http://sqs.data"

    settings = AppSettings()
    assert settings.database.global_url == "postgres://global"
    assert settings.aws.region == "us-west-2"
    assert settings.sqs.data_plane_jobs_queue_url == "http://sqs.data"

    del os.environ["DATABASE_GLOBAL_URL"]
    del os.environ["AWS_REGION"]
    del os.environ["SQS_DATA_PLANE_JOBS_QUEUE_URL"]
