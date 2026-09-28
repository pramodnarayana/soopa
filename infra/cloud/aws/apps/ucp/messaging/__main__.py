"""
Application Layer (Layer 3) - UCP Bounded Context: Messaging
=============================================================
Provisions all UCP-specific messaging infrastructure:
- UCP SQS Queues (ucp-events, ucp-jobs)

Driven entirely by topology.json. Exports a single structured ``queue_env_vars``
map so compute stacks can do zero-touch environment variable injection.
"""

import pulumi
from infra_seedwork.messaging import provision_from_topology
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-ucp-"
_TAGS = {"ManagedBy": "pulumi", "Component": "ucp", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

# ── Topology ──────────────────────────────────────────────────────────────────
topology = load_topology()

platform_events_topic_arn = platform.require_output("sns_platform_events_topic_arn")

result = provision_from_topology(
    topology=topology,
    prefix=_prefix,
    tags=_TAGS,
    queue_filter={"ucp-events", "ucp-jobs"},
    topic_filter=set(),  # UCP owns no topics
    external_topic_arns={"platform-events-topic": platform_events_topic_arn},
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("queue_env_vars", result.queue_env_vars)

# Granular exports for stacks still using individual require_output() calls.
pulumi.export("ucp_events_topic_arn", platform_events_topic_arn)
pulumi.export("ucp_jobs_queue_url", result.queues["ucp-jobs"].url)
