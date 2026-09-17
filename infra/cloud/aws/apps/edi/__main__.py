"""
Application Layer (Layer 3) - EDI Bounded Context
===================================================
Provisions all EDI-specific infrastructure:
- EDI S3 Buckets (Payloads)
- EDI SQS Queues & SNS Topics (Messaging)
- EDI ECS Services (AS2 Server, Compute Worker, etc.)

Relies on Foundation and Platform StackReferences.
"""

import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
from compute import provision_compute
from messaging import provision_messaging
from storage import provision_storage

_env = pulumi.get_stack()
_prefix = f"{_env}-edi-"
_TAGS = {"ManagedBy": "pulumi", "Component": "edi", "Environment": _env}

# ── Stack References ──────────────────────────────────────────────────────────
config = pulumi.Config()

# Retrieve fully qualified StackReference names from config, or fallback to sensible defaults
# This allows testing the 'prod' EDI app against a 'dev' Foundation layer if needed.
foundation_stack_ref = config.get("foundation_stack") or f"foundation/{_env}"
platform_stack_ref = config.get("platform_stack") or f"platform/{_env}"

foundation = pulumi.StackReference(foundation_stack_ref)
platform = pulumi.StackReference(platform_stack_ref)

vpc_id = foundation.require_output("vpc_id")
private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
public_subnets = [
    foundation.require_output("public_subnet_a_id"),
    foundation.require_output("public_subnet_b_id"),
]
app_sg_id = foundation.require_output("app_sg_id")

ecs_cluster_arn = platform.require_output("ecs_cluster_arn")
ecr_repository_url = platform.require_output("ecr_repository_url")
main_alb_listener_arn = platform.require_output("main_alb_listener_arn")

# Since we haven't built an image yet in CI, we use a placeholder image for IaC deployment validation.
# In a real environment, this gets updated dynamically by GitHub Actions.
image_tag = config.get("image_tag") or "latest"
enable_observability = config.get_bool("enable_observability")
firelens_endpoint = (
    platform.require_output("openobserve_endpoint") if enable_observability else None
)
placeholder_image = pulumi.Output.concat(ecr_repository_url, f":{image_tag}")

# ── Provision Domain Resources ────────────────────────────────────────────────
storage = provision_storage(_prefix, _TAGS)
messaging = provision_messaging(_prefix, _TAGS)

compute = provision_compute(
    prefix=_prefix,
    tags=_TAGS,
    vpc_id=vpc_id,
    private_subnets=private_subnets,
    public_subnets=public_subnets,
    app_sg_id=app_sg_id,
    cluster_arn=ecs_cluster_arn,
    ecr_image_uri=placeholder_image,
    queues=messaging["queues"],
    alb_listener_arn=main_alb_listener_arn,
    firelens_endpoint=firelens_endpoint,
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("edi_payloads_bucket", storage.id)
pulumi.export("edi_events_topic_arn", messaging["edi_events_topic"].arn)
pulumi.export("edi_data_plane_jobs_queue_url", messaging["queues"]["data_plane_jobs"].url)
pulumi.export("edi_control_plane_jobs_queue_url", messaging["queues"]["control_plane_jobs"].url)
