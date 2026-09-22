"""
Application Layer (Layer 3) - Notification Bounded Context
==========================================================
Provisions all Notification-specific infrastructure:
- Notification SQS Queues (email-channel)

Workers have been consolidated to the unified workers stack.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
from seedwork.messaging import provision_fifo_queue_pair

_env = pulumi.get_stack()
_prefix = f"{_env}-notification-"
_TAGS = {"ManagedBy": "pulumi", "Component": "notification", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()
edi_stack_ref = config.get("edi_stack") or f"edi/{_env}"
edi = pulumi.StackReference(edi_stack_ref)

# ── Messaging ─────────────────────────────────────────────────────────────────
email_channel_q, _ = provision_fifo_queue_pair(f"{_prefix}email-channel", _TAGS)
notification_jobs_q, _ = provision_fifo_queue_pair(f"{_prefix}notification-jobs", _TAGS)
edi_priority_notifications_q = edi.require_output("edi_priority_notifications_queue_url")

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("email_channel_queue_url", email_channel_q.url)
pulumi.export("notification_jobs_queue_url", notification_jobs_q.url)
