"""Unit tests for decentralized topology manifest composition and IP scheduled jobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ip.engine.domain.enums import IpJobName
from scripts.seed_jobs import (
    IP_CONTROL_PLANE_JOBS_QUEUE,
    IP_DATA_PLANE_JOBS_QUEUE,
    build_ip_scheduled_jobs,
)
from sync_topology import (
    build_env_mappings,
    compose_topology_manifests,
    resolve_topology_paths,
    sync_topology,
)

REPO_ROOT = Path(__file__).resolve().parents[6]


def test_resolve_topology_paths_for_all_and_single_domains() -> None:
    all_paths = resolve_topology_paths(REPO_ROOT, "all")
    rel_all = [str(p.relative_to(REPO_ROOT)) for p in all_paths]
    assert rel_all == [
        "core/platform/topology.json",
        "apps/edi/topology.json",
        "apps/ip/topology.json",
    ]

    ip_paths = resolve_topology_paths(REPO_ROOT, "platform,ip")
    rel_ip = [str(p.relative_to(REPO_ROOT)) for p in ip_paths]
    assert rel_ip == [
        "core/platform/topology.json",
        "apps/ip/topology.json",
    ]

    edi_paths = resolve_topology_paths(REPO_ROOT, "platform,edi")
    rel_edi = [str(p.relative_to(REPO_ROOT)) for p in edi_paths]
    assert rel_edi == [
        "core/platform/topology.json",
        "apps/edi/topology.json",
    ]


def test_resolve_topology_paths_rejects_unknown_domain() -> None:
    with pytest.raises(FileNotFoundError, match="Topology manifest for domain 'nonexistent'"):
        resolve_topology_paths(REPO_ROOT, "platform,nonexistent")


def test_compose_topology_manifests_and_build_env_mappings_ip_only() -> None:
    ip_paths = resolve_topology_paths(REPO_ROOT, "platform,ip")
    composed = compose_topology_manifests(ip_paths)

    queue_names = {str(q["name"]) for q in composed["queues"]}
    assert "ip-orchestrator-realtime" in queue_names
    assert "ip-orchestrator-bulk" in queue_names
    assert "ip-delivery-realtime" in queue_names
    assert "ip-delivery-bulk" in queue_names
    assert "ip-control-plane-jobs" in queue_names
    assert "ip-data-plane-jobs" in queue_names
    assert "edi-compute" not in queue_names

    mappings = build_env_mappings(composed)
    assert (
        mappings["SQS_IP_ORCHESTRATOR_REALTIME_QUEUE_URL"]
        == "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ip-orchestrator-realtime"
    )
    assert (
        mappings["SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL"]
        == "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/ip-control-plane-jobs.fifo"
    )
    assert (
        mappings["SNS_IP_EVENTS_TOPIC_ARN"] == "arn:aws:sns:us-east-1:000000000000:ip-events-topic"
    )
    assert "SQS_EDI_COMPUTE_QUEUE_URL" not in mappings


def test_sync_topology_writes_composed_manifest_and_updates_env(tmp_path: Path) -> None:
    (tmp_path / "core" / "platform").mkdir(parents=True)
    (tmp_path / "apps" / "ip").mkdir(parents=True)
    (tmp_path / "infra").mkdir(parents=True)

    (tmp_path / "core" / "platform" / "topology.json").write_text(
        json.dumps(
            {
                "topics": [{"name": "platform-topic", "fifo": True}],
                "queues": [{"name": "identity-jobs", "fifo": True}],
                "subscriptions": [],
                "buckets": [],
                "secrets": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "apps" / "ip" / "topology.json").write_text(
        json.dumps(
            {
                "topics": [
                    {"name": "ip-events-topic", "fifo": True, "env_var": "SNS_IP_EVENTS_TOPIC_ARN"}
                ],
                "queues": [
                    {
                        "name": "ip-data-plane-jobs",
                        "fifo": True,
                        "env_var": "SQS_IP_DATA_PLANE_JOBS_QUEUE_URL",
                    }
                ],
                "subscriptions": [],
                "buckets": [{"name": "ip-payloads"}],
                "secrets": [],
            }
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("SQS_IDENTITY_JOBS_QUEUE_URL=old\n", encoding="utf-8")

    mappings = sync_topology(tmp_path, domains="platform,ip")
    assert "SQS_IP_DATA_PLANE_JOBS_QUEUE_URL" in mappings
    assert "SNS_IP_EVENTS_TOPIC_ARN" in mappings

    composed_file = tmp_path / "infra" / "topology.json"
    assert composed_file.exists()
    composed_data = json.loads(composed_file.read_text(encoding="utf-8"))
    assert [q["name"] for q in composed_data["queues"]] == [
        "identity-jobs",
        "ip-data-plane-jobs",
    ]

    env_text = env_file.read_text(encoding="utf-8")
    assert "SQS_IP_DATA_PLANE_JOBS_QUEUE_URL=" in env_text
    assert "SNS_IP_EVENTS_TOPIC_ARN=" in env_text


def test_build_ip_scheduled_jobs_returns_all_five_canonical_jobs() -> None:
    fixed_now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
    jobs = build_ip_scheduled_jobs(fixed_now)
    assert len(jobs) == 5

    by_name = {str(job["name"]): job for job in jobs}
    assert set(by_name.keys()) == {
        IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value,
        IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value,
        IpJobName.IP_CONTROL_PLANE_OUTBOX_CLEANUP.value,
        IpJobName.IP_DATA_PLANE_OUTBOX_CLEANUP.value,
        IpJobName.IP_DATA_RETENTION_CLEANUP.value,
    }
    assert (
        by_name[IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value]["target_queue"]
        == IP_CONTROL_PLANE_JOBS_QUEUE
    )
    assert (
        by_name[IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value]["target_queue"]
        == IP_DATA_PLANE_JOBS_QUEUE
    )
    assert (
        by_name[IpJobName.IP_DATA_RETENTION_CLEANUP.value]["target_queue"]
        == IP_DATA_PLANE_JOBS_QUEUE
    )
