import pytest
from database.utils import normalize_to_asyncpg

from scheduler_worker.config.settings import (
    AppSettings,
    discover_jobs_queue_url_map,
    extract_physical_queue_name,
)


def test_settings_load_nested_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://global")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv(
        "SQS_DATA_PLANE_JOBS_QUEUE_URL",
        "http://sqs.us-east-1.localhost:4566/000000000000/edi-data-plane-jobs.fifo",
    )
    monkeypatch.setenv(
        "SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL",
        "http://sqs.us-east-1.localhost:4566/000000000000/ip-control-plane-jobs.fifo",
    )
    monkeypatch.setenv(
        "SQS_IP_DATA_PLANE_JOBS_QUEUE_URL",
        "http://sqs.us-east-1.localhost:4566/000000000000/ip-data-plane-jobs.fifo",
    )

    settings = AppSettings(_env_file=None)

    assert settings.database.global_url == normalize_to_asyncpg("postgres://global")
    assert settings.aws.region == "us-west-2"
    assert (
        settings.sqs.data_plane_jobs_queue_url
        == "http://sqs.us-east-1.localhost:4566/000000000000/edi-data-plane-jobs.fifo"
    )
    assert (
        settings.sqs_queue_url_map["edi-data-plane-jobs.fifo"]
        == "http://sqs.us-east-1.localhost:4566/000000000000/edi-data-plane-jobs.fifo"
    )
    assert (
        settings.sqs_queue_url_map["ip-control-plane-jobs.fifo"]
        == "http://sqs.us-east-1.localhost:4566/000000000000/ip-control-plane-jobs.fifo"
    )
    assert (
        settings.sqs_queue_url_map["ip-data-plane-jobs.fifo"]
        == "http://sqs.us-east-1.localhost:4566/000000000000/ip-data-plane-jobs.fifo"
    )


def test_discover_jobs_queue_url_map_is_domain_agnostic() -> None:
    assert extract_physical_queue_name("") == ""
    assert (
        extract_physical_queue_name("http://sqs.local/000000000000/ip-data-plane-jobs.fifo/")
        == "ip-data-plane-jobs.fifo"
    )
    discovered = discover_jobs_queue_url_map(
        {
            "SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL": "http://sqs.local/000000000000/ip-control-plane-jobs.fifo",
            "SQS_FUTURE_BILLING_JOBS_QUEUE_URL": "http://sqs.local/000000000000/billing-jobs.fifo",
            "SQS_DELIVER_QUEUE_URL": "http://sqs.local/000000000000/edi-deliver",
        }
    )
    assert discovered == {
        "ip-control-plane-jobs.fifo": "http://sqs.local/000000000000/ip-control-plane-jobs.fifo",
        "billing-jobs.fifo": "http://sqs.local/000000000000/billing-jobs.fifo",
    }
