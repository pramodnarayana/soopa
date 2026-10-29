"""Composes per-domain topology.json manifests and synchronizes active URLs/ARNs to .env."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

LOCALSTACK_SQS_URL = "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/"
LOCALSTACK_SNS_ARN = "arn:aws:sns:us-east-1:000000000000:"


def resolve_topology_paths(root_dir: Path, domains_arg: str) -> list[Path]:
    """Resolves the ordered list of per-domain topology.json manifests to compose."""
    platform_manifest = root_dir / "core" / "platform" / "topology.json"
    if not platform_manifest.exists():
        raise FileNotFoundError(f"Core platform topology manifest not found: {platform_manifest}")

    paths: list[Path] = [platform_manifest]
    apps_dir = root_dir / "apps"

    normalized = domains_arg.strip().lower()
    if normalized in ("all", ""):
        if apps_dir.exists():
            for app_manifest in sorted(apps_dir.glob("*/topology.json")):
                paths.append(app_manifest)
        return paths

    requested_domains = [
        token.strip().lower()
        for token in normalized.split(",")
        if token.strip() and token.strip().lower() != "platform"
    ]
    for app_name in requested_domains:
        candidate = apps_dir / app_name / "topology.json"
        if not candidate.exists():
            raise FileNotFoundError(
                f"Topology manifest for domain '{app_name}' not found at {candidate}"
            )
        paths.append(candidate)

    return paths


def compose_topology_manifests(
    manifest_paths: Sequence[Path],
) -> dict[str, list[dict[str, object]]]:
    """Merges multiple per-domain topology.json manifests into a single deduplicated topology."""
    composed: dict[str, list[dict[str, object]]] = {
        "topics": [],
        "queues": [],
        "subscriptions": [],
        "buckets": [],
        "secrets": [],
    }
    seen_names: dict[str, set[str]] = {
        "topics": set(),
        "queues": set(),
        "buckets": set(),
        "secrets": set(),
    }
    seen_subscriptions: set[tuple[str, str]] = set()

    for path in manifest_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("topics", "queues", "buckets", "secrets"):
            for item in data.get(section, []):
                name = str(item.get("name", ""))
                if name and name not in seen_names[section]:
                    seen_names[section].add(name)
                    composed[section].append(item)

        for sub in data.get("subscriptions", []):
            key = (str(sub.get("topic", "")), str(sub.get("queue", "")))
            if key not in seen_subscriptions:
                seen_subscriptions.add(key)
                composed["subscriptions"].append(sub)

    return composed


def build_env_mappings(topology: dict[str, list[dict[str, object]]]) -> dict[str, str]:
    """Builds .env variable mappings for all queues (including DLQs) and topics in topology."""
    mappings: dict[str, str] = {}

    for queue in topology.get("queues", []):
        name = str(queue["name"])
        is_fifo = bool(queue.get("fifo", False))
        physical_name = f"{name}.fifo" if is_fifo else name
        default_env_var = f"SQS_{name.upper().replace('-', '_')}_QUEUE_URL"
        env_var_name = str(queue.get("env_var") or default_env_var)
        mappings[env_var_name] = f"{LOCALSTACK_SQS_URL}{physical_name}"

        dlq_env_var = queue.get("dlq_env_var")
        if isinstance(dlq_env_var, str) and dlq_env_var:
            dlq_physical_name = f"{name}-dlq.fifo" if is_fifo else f"{name}-dlq"
            mappings[dlq_env_var] = f"{LOCALSTACK_SQS_URL}{dlq_physical_name}"

    for topic in topology.get("topics", []):
        name = str(topic["name"])
        is_fifo = bool(topic.get("fifo", False))
        physical_name = f"{name}.fifo" if is_fifo else name
        default_env_var = f"SNS_{name.upper().replace('-', '_')}_TOPIC_ARN"
        env_var_name = str(topic.get("env_var") or default_env_var)
        mappings[env_var_name] = f"{LOCALSTACK_SNS_ARN}{physical_name}"

    return mappings


def sync_topology(
    root_dir: Path,
    domains: str = "all",
) -> dict[str, str]:
    """Composes per-domain topology manifests, writes infra/topology.json, and syncs .env."""
    env_path = root_dir / ".env"
    if not env_path.exists():
        logger.error("topology_sync_env_missing", env_path=str(env_path))
        raise FileNotFoundError(f".env file not found at {env_path}")

    manifest_paths = resolve_topology_paths(root_dir, domains)
    topology = compose_topology_manifests(manifest_paths)

    composed_path = root_dir / "infra" / "topology.json"
    composed_path.write_text(json.dumps(topology, indent=2) + "\n", encoding="utf-8")
    logger.info(
        "topology_composed_manifest_written",
        output_path=str(composed_path),
        manifests=[str(p.relative_to(root_dir)) for p in manifest_paths],
    )

    mappings = build_env_mappings(topology)
    env_content = env_path.read_text(encoding="utf-8")

    for key, value in mappings.items():
        pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
        if pattern.search(env_content):
            env_content = pattern.sub(f"{key}={value}", env_content)
        else:
            if not env_content.endswith("\n"):
                env_content += "\n"
            env_content += f"{key}={value}\n"

    env_path.write_text(env_content, encoding="utf-8")
    logger.info(
        "topology_synced_to_env",
        domains=domains,
        synced_key_count=len(mappings),
    )
    return mappings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose per-domain topology.json manifests and sync URLs to .env"
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=os.environ.get("ENABLED_APPS", "all"),
        help="Comma-separated domains to compose (e.g. 'platform,ip', 'platform,edi', or 'all')",
    )
    parsed = parser.parse_args(argv)

    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parents[2]
    try:
        sync_topology(root_dir=root_dir, domains=parsed.domains)
        return 0
    except Exception as exc:
        logger.exception("topology_sync_failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
