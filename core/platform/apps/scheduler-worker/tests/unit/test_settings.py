from database.utils import normalize_to_asyncpg
from seedwork.infra.config_models import PlatformAwsSettings, PlatformDatabaseSettings

from scheduler_worker.config.settings import (
    AppSettings,
    SqsSettings,
    discover_jobs_queue_url_map,
    extract_physical_queue_name,
    parse_active_namespaces,
)


def test_settings_pure_instantiation() -> None:
    db = PlatformDatabaseSettings(_env_file=None, DATABASE_URL="postgres://global")
    aws = PlatformAwsSettings(_env_file=None, AWS_REGION="us-west-2")
    sqs = SqsSettings(
        _env_file=None,
        SQS_DATA_PLANE_JOBS_QUEUE_URL="http://sqs.us-east-1.localhost:4566/000000000000/edi-data-plane-jobs.fifo",
        SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL="http://sqs.us-east-1.localhost:4566/000000000000/ip-control-plane-jobs.fifo",
        SQS_IP_DATA_PLANE_JOBS_QUEUE_URL="http://sqs.us-east-1.localhost:4566/000000000000/ip-data-plane-jobs.fifo",
    )
    settings = AppSettings(
        _env_file=None,
        enabled_apps="edi",
        database=db,
        aws=aws,
        sqs=sqs,
    )

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
    assert settings.active_namespaces == ["platform", "edi"]


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


def test_parse_active_namespaces_pure_logic() -> None:
    # 1. None, empty, or whitespace -> None (all claimable)
    assert parse_active_namespaces(None) is None
    assert parse_active_namespaces("") is None
    assert parse_active_namespaces("   ") is None

    # 2. Wildcard "*" -> None (all claimable)
    assert parse_active_namespaces("*") is None
    assert parse_active_namespaces(" * ") is None

    # 3. Single app "edi" -> ["platform", "edi"]
    assert parse_active_namespaces("edi") == ["platform", "edi"]
    assert parse_active_namespaces("EDI") == ["platform", "edi"]

    # 4. Multi-app with spaces & deduplication -> ["platform", "edi", "ip"]
    assert parse_active_namespaces(" EDI , ip , edi ") == ["platform", "edi", "ip"]
