"""
Application Layer (Layer 3) - Identity Bounded Context: Messaging
=================================================================
Provisions all Identity-specific messaging infrastructure:
- Identity SQS Queues (identity-events, identity-jobs)

Driven entirely by topology.json. Exports a single structured ``queue_env_vars``
map so compute stacks can do zero-touch environment variable injection.
"""

import pulumi
from infra_seedwork.messaging import provision_from_topology
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-identity-"
_TAGS = {"ManagedBy": "pulumi", "Component": "identity", "Environment": _env}

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
    queue_filter={"identity-events", "identity-jobs"},
    topic_filter=set(),  # Identity owns no topics
    external_topic_arns={"platform-events-topic": platform_events_topic_arn},
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("queue_env_vars", result.queue_env_vars)

# Granular exports for stacks still using individual require_output() calls.
pulumi.export("identity_events_topic_arn", platform_events_topic_arn)
pulumi.export("identity_events_queue_url", result.queues["identity-events"].url)
pulumi.export("identity_events_queue_arn", result.queues["identity-events"].arn)
pulumi.export("identity_jobs_queue_url", result.queues["identity-jobs"].url)
pulumi.export("identity_jobs_queue_arn", result.queues["identity-jobs"].arn)
