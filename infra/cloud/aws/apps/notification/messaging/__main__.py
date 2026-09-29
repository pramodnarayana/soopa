"""
Application Layer (Layer 3) - Notification Bounded Context: Messaging
======================================================================
Provisions all Notification-specific messaging infrastructure:
- Notification SQS Queues (notification-jobs, email-channel)

Driven entirely by topology.json. Exports a single structured ``queue_env_vars``
map so compute stacks can do zero-touch environment variable injection.
"""

import pulumi
from infra_seedwork.messaging import provision_from_topology
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-notification-"
_TAGS = {"ManagedBy": "pulumi", "Component": "notification", "Environment": _env}

# ── Topology ──────────────────────────────────────────────────────────────────
topology = load_topology()

result = provision_from_topology(
    topology=topology,
    prefix=_prefix,
    tags=_TAGS,
    queue_filter={"notification-jobs", "email-channel"},
    topic_filter=set(),  # Notification owns no topics
)

# Guard: fail fast if topology.json no longer declares the expected queues.
_expected_queues = {"notification-jobs", "email-channel"}
_missing = _expected_queues - set(result.queues.keys())
if _missing:
    raise ValueError(
        f"Notification messaging: expected queues not provisioned: {_missing}. "
        "Check that topology.json still declares them with the correct names."
    )

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("queue_env_vars", result.queue_env_vars)

# Granular exports for stacks still using individual require_output() calls.
pulumi.export("email_channel_queue_url", result.queues["email-channel"].url)
pulumi.export("notification_jobs_queue_url", result.queues["notification-jobs"].url)
