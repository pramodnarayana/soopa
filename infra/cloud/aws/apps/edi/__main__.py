"""
Application Layer (Layer 3) - EDI Bounded Context
===================================================
Provisions all EDI-specific infrastructure:
- EDI S3 Buckets (Payloads)
- EDI SQS Queues & SNS Topics (Messaging)
- EDI ECS Services (AS2 Server, Compute Worker, etc.)

Relies on Foundation and Platform StackReferences.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("../../packages"))

import pulumi
from compute import provision_compute
from messaging import provision_messaging

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
edi_shard_db_endpoint = platform.require_output("edi_shard_db_endpoint")
edi_shard_db_secret_arn = platform.require_output("edi_shard_db_secret_arn")

topology_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../topology.json")
)
with open(topology_path) as f:
    topology = json.load(f)

external_topics = {}
for topic in topology.get("topics", []):
    name = topic["name"]
    if not name.startswith("edi-"):
        output_name = f"sns_{name.replace('-', '_')}_arn"
        external_topics[name] = platform.require_output(output_name)

# ── Provision Domain Resources ────────────────────────────────────────────────
messaging = provision_messaging(
    _prefix,
    _TAGS,
    topology=topology,
    external_topics=external_topics,
)

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
    topics=messaging["topics"],
    edi_shard_db_endpoint=edi_shard_db_endpoint,
    edi_shard_db_secret_arn=edi_shard_db_secret_arn,
)

# ── Exports ───────────────────────────────────────────────────────────────────
for topic_name, topic in messaging["topics"].items():
    pulumi.export(f"sns_{topic_name.replace('-', '_')}_arn", topic.arn)

for queue_name, queue in messaging["queues"].items():
    pulumi.export(f"sqs_{queue_name.replace('-', '_')}_url", queue.url)
