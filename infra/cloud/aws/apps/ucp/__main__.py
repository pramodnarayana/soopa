"""
Application Layer (Layer 3) - UCP Bounded Context
===================================================
Provisions all UCP-specific infrastructure:
- UCP SQS Queues & SNS Topics (Messaging)

Workers have been consolidated to the unified workers stack.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
from seedwork.messaging import provision_fifo_queue_pair, subscribe_queue

_env = pulumi.get_stack()
_prefix = f"{_env}-ucp-"
_TAGS = {"ManagedBy": "pulumi", "Component": "ucp", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"
platform = pulumi.StackReference(platform_stack_ref)

# ── Messaging ─────────────────────────────────────────────────────────────────
platform_events_topic_arn = platform.require_output("sns_platform_events_topic_arn")

events_q, _ = provision_fifo_queue_pair(f"{_prefix}events", _TAGS)
jobs_q, _ = provision_fifo_queue_pair(f"{_prefix}jobs", _TAGS)

subscribe_queue(f"{_prefix}events-sub", platform_events_topic_arn, events_q)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("ucp_events_topic_arn", platform_events_topic_arn)
pulumi.export("ucp_jobs_queue_url", jobs_q.url)
