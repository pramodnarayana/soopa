"""
Application Layer (Layer 3) - EDI Bounded Context: Messaging
=============================================================
Provisions EDI-specific messaging infrastructure only:
- EDI SQS Queues
- EDI SNS Topics
- SNS Subscriptions

Driven entirely by topology.json. Exports a single structured ``queue_env_vars``
map so compute stacks can do zero-touch environment variable injection.
"""

import pulumi
from infra_seedwork.messaging import provision_from_topology
from infra_seedwork.topology import load_topology

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi-messaging", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"organization/platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

# ── Topology ──────────────────────────────────────────────────────────────────
topology = load_topology()

# EDI owns all queues/topics prefixed with "edi-".
edi_queues = {q["name"] for q in topology["queues"] if q["name"].startswith("edi-")}
edi_topics = {t["name"] for t in topology["topics"] if t["name"].startswith("edi-")}

# The platform-events-topic is owned by the platform stack; we reference it for
# subscriptions but do not re-provision it here.
platform_events_topic_arn = platform.require_output("sns_platform_events_topic_arn")

result = provision_from_topology(
    topology=topology,
    prefix=_prefix,
    tags=_TAGS,
    queue_filter=edi_queues,
    topic_filter=edi_topics,
    external_topic_arns={"platform-events-topic": platform_events_topic_arn},
)

# ── Exports ───────────────────────────────────────────────────────────────────
# Structured SSOT exports: compute stacks consume queue_env_vars (for container
# env injection) and queue_arns (for least-privilege SQS IAM permissions).
pulumi.export("queue_env_vars", result.queue_env_vars)
pulumi.export("queue_arns", result.queue_arns)

for queue_name, queue in result.queues.items():
    pulumi.export(f"sqs_{queue_name.replace('-', '_')}_url", queue.url)
    pulumi.export(f"sqs_{queue_name.replace('-', '_')}_arn", queue.arn)
for topic_name, topic in result.topics.items():
    pulumi.export(f"sns_{topic_name.replace('-', '_')}_arn", topic.arn)
