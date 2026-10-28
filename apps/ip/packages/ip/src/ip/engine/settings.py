"""Strongly-typed Pydantic Settings for the Integration Platform (IP) Engine & Workers."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IpEngineSettings(BaseSettings):
    """Unified configuration for IP Engine API, Orchestrator, Delivery, and Jobs workers.

    Reads strictly from environment variables / `.env` in compliance with Shopify-style
    single-image deployment and IaC URL injection standards.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Database
    global_database_url: str = Field(
        default="",
        validation_alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=10, validation_alias="IP_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, validation_alias="IP_DB_MAX_OVERFLOW")

    # AWS & LocalStack transport
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    aws_endpoint_url: str | None = Field(default=None, validation_alias="AWS_ENDPOINT_URL")
    aws_access_key_id: str | None = Field(default=None, validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY"
    )

    # Two-Lane Priority SQS Queue URLs & SNS Topic ARNs (IaC Injected)
    ip_orchestrator_realtime_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_ORCHESTRATOR_REALTIME_QUEUE_URL",
            "IP_ORCHESTRATOR_REALTIME_QUEUE_URL",
        ),
    )
    ip_orchestrator_bulk_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_ORCHESTRATOR_BULK_QUEUE_URL",
            "IP_ORCHESTRATOR_BULK_QUEUE_URL",
        ),
    )
    ip_delivery_realtime_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_DELIVERY_REALTIME_QUEUE_URL",
            "IP_DELIVERY_REALTIME_QUEUE_URL",
        ),
    )
    ip_delivery_bulk_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_DELIVERY_BULK_QUEUE_URL",
            "IP_DELIVERY_BULK_QUEUE_URL",
        ),
    )
    ip_control_plane_jobs_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL",
            "IP_CONTROL_PLANE_JOBS_QUEUE_URL",
        ),
    )
    ip_data_plane_jobs_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_IP_DATA_PLANE_JOBS_QUEUE_URL",
            "IP_DATA_PLANE_JOBS_QUEUE_URL",
        ),
    )
    ip_events_topic_arn: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SNS_IP_EVENTS_TOPIC_ARN",
            "IP_EVENTS_TOPIC_ARN",
        ),
    )
    notification_queue_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SQS_NOTIFICATION_JOBS_QUEUE_URL",
            "NOTIFICATION_QUEUE_URL",
        ),
    )

    # Worker Concurrency & SQS Polling
    orchestrator_realtime_max_messages: int = Field(
        default=10,
        validation_alias="IP_ORCHESTRATOR_REALTIME_MAX_MESSAGES",
    )
    orchestrator_bulk_max_messages: int = Field(
        default=5,
        validation_alias="IP_ORCHESTRATOR_BULK_MAX_MESSAGES",
    )
    orchestrator_chunk_concurrency: int = Field(
        default=20,
        validation_alias="IP_ORCHESTRATOR_CHUNK_CONCURRENCY",
    )
    delivery_realtime_max_messages: int = Field(
        default=10,
        validation_alias="IP_DELIVERY_REALTIME_MAX_MESSAGES",
    )
    delivery_bulk_max_messages: int = Field(
        default=5,
        validation_alias="IP_DELIVERY_BULK_MAX_MESSAGES",
    )
    delivery_chunk_concurrency: int = Field(
        default=10,
        validation_alias="IP_DELIVERY_CHUNK_CONCURRENCY",
    )
    sqs_visibility_timeout_sec: int = Field(
        default=60,
        validation_alias="IP_SQS_VISIBILITY_TIMEOUT_SEC",
    )
    sqs_wait_time_seconds: int = Field(
        default=20,
        validation_alias="IP_SQS_WAIT_TIME_SECONDS",
    )

    # Outbox Relay, Sweeper, & Retention
    outbox_batch_size: int = Field(
        default=200,
        validation_alias="IP_OUTBOX_BATCH_SIZE",
    )
    outbox_lock_lease_ms: int = Field(
        default=30000,
        validation_alias="IP_OUTBOX_LOCK_LEASE_MS",
    )
    outbox_fallback_poll_sec: float = Field(
        default=5.0,
        validation_alias="IP_OUTBOX_FALLBACK_POLL_SEC",
    )
    outbox_sweeper_cron: str = Field(
        default="*/1 * * * *",
        validation_alias="IP_OUTBOX_SWEEPER_CRON",
    )
    outbox_retention_cron: str = Field(
        default="0 * * * *",
        validation_alias="IP_OUTBOX_RETENTION_CRON",
    )
    outbox_retention_hours: int = Field(
        default=168,
        validation_alias="IP_OUTBOX_RETENTION_HOURS",
    )
    trace_retention_cron: str = Field(
        default="30 2 * * *",
        validation_alias="IP_TRACE_RETENTION_CRON",
    )
    trace_retention_days: int = Field(
        default=30,
        validation_alias="IP_TRACE_RETENTION_DAYS",
    )
    stitch_tick_interval_sec: float = Field(
        default=2.0,
        validation_alias="IP_STITCH_TICK_INTERVAL_SEC",
    )
    allow_private_ips: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "ALLOW_PRIVATE_IPS",
            "IP_ALLOW_PRIVATE_IPS",
            "EDI_ALLOW_PRIVATE_IPS",
        ),
    )


@lru_cache(maxsize=1)
def get_ip_engine_settings() -> IpEngineSettings:
    """Returns a cached singleton of IpEngineSettings."""
    return IpEngineSettings()


__all__ = ["IpEngineSettings", "get_ip_engine_settings"]
