"""
Application Layer (Layer 3) - Identity Bounded Context
======================================================
Provisions all Identity-specific infrastructure:
- Identity SQS Queues & SNS Topics (Messaging)

Workers have been consolidated to the unified workers stack.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
from seedwork.messaging import provision_fifo_queue_pair, subscribe_queue

_env = pulumi.get_stack()
_prefix = f"{_env}-identity-"
_TAGS = {"ManagedBy": "pulumi", "Component": "identity", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

# ── Messaging ─────────────────────────────────────────────────────────────────
sns_platform_events_topic_arn = platform.require_output("sns_platform_events_topic_arn")

events_q, _ = provision_fifo_queue_pair(f"{_prefix}events", _TAGS)
jobs_q, _ = provision_fifo_queue_pair(f"{_prefix}jobs", _TAGS)

subscribe_queue(
    f"{_prefix}events-sub",
    sns_platform_events_topic_arn,
    events_q,
    filter_policy=json.dumps(
        {
            "event_type": [
                {"prefix": "tenant."},
                {"prefix": "app."},
                {"prefix": "user."},
            ]
        }
    ),
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("identity_events_topic_arn", sns_platform_events_topic_arn)
pulumi.export("identity_jobs_queue_url", jobs_q.url)
