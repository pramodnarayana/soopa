"""
Data Layer (Layer 2)
====================
Provisions stateful data persistence resources:
- Global RDS PostgreSQL Database
- EDI Shard PostgreSQL Database
"""

import pulumi
import pulumi_aws as aws
from edi_db import provision_edi_db
from global_db import provision_global_db
from infra_seedwork import DatabaseConstants

_env = pulumi.get_stack()
_prefix = f"{_env}-"
_TAGS = {"ManagedBy": "pulumi", "Component": "data", "Environment": _env}

# ── Stack Reference to Foundation ─────────────────────────────────────────────
config = pulumi.Config()
foundation_stack_ref = config.get("foundation_stack") or f"organization/foundation/{_env}"
foundation = pulumi.StackReference(foundation_stack_ref)

private_subnets = [
    foundation.require_output("private_subnet_a_id"),
    foundation.require_output("private_subnet_b_id"),
]
db_sg_id = foundation.require_output("db_sg_id")

# ── Shared DB Subnet Group ────────────────────────────────────────────────────
db_subnet_group = aws.rds.SubnetGroup(
    f"{_prefix}db-subnet-group",
    subnet_ids=private_subnets,
    tags=_TAGS,
)

is_prod = _env == "production"
default_instance = (
    DatabaseConstants.DEFAULT_PROD_INSTANCE_CLASS
    if is_prod
    else DatabaseConstants.DEFAULT_NON_PROD_INSTANCE_CLASS
)
instance_class = config.get("db_instance_class") or default_instance
allocated_storage = (
    config.get_int("db_allocated_storage") or DatabaseConstants.DEFAULT_ALLOCATED_STORAGE_GB
)
multi_az = config.get_bool("multi_az")
if multi_az is None:
    multi_az = is_prod

# ── Provision Global Database ─────────────────────────────────────────────────
global_db, db_secret, db_password = provision_global_db(
    prefix=_prefix,
    db_subnet_group_name=db_subnet_group.name,
    db_sg_id=db_sg_id,
    tags=_TAGS,
    instance_class=instance_class,
    allocated_storage=allocated_storage,
    multi_az=multi_az,
)

# ── Provision EDI Shard Database ──────────────────────────────────────────────
edi_shard_db, edi_db_secret = provision_edi_db(
    prefix=_prefix,
    db_subnet_group_name=db_subnet_group.name,
    db_sg_id=db_sg_id,
    tags=_TAGS,
    instance_class=instance_class,
    allocated_storage=allocated_storage,
    multi_az=multi_az,
)

# ── Exports ───────────────────────────────────────────────────────────────────
pulumi.export("global_db_endpoint", global_db.endpoint)
pulumi.export("global_db_secret_arn", db_secret.arn)
pulumi.export("global_db_secret_name", db_secret.name)
pulumi.export("global_db_password", db_password.result)

pulumi.export("edi_shard_db_endpoint", edi_shard_db.endpoint)
pulumi.export("edi_shard_db_secret_arn", edi_db_secret.arn)
