import json

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import DatabaseConstants


def provision_edi_db(
    prefix: str,
    db_subnet_group_name: str,
    db_sg_id: str,
    tags: dict,
    instance_class: str,
    allocated_storage: int,
):
    edi_db_password = random.RandomPassword(
        "edi-shard-db-password",
        length=32,
        override_special="!#$%^&*()-_=+[]{}|;:,.<>?",
    )

    # Custom Parameter Group for Debezium Logical Replication
    edi_db_parameter_group = aws.rds.ParameterGroup(
        f"{prefix}edi-shard-db-pg",
        family="postgres15",
        parameters=[
            aws.rds.ParameterGroupParameterArgs(
                name="rds.logical_replication",
                value="1",
                apply_method="pending-reboot",
            )
        ],
        tags=tags,
    )

    edi_shard_db = aws.rds.Instance(
        f"{prefix}edi-shard-db",
        identifier=f"{prefix}edi-shard-db",
        engine=DatabaseConstants.ENGINE,
        engine_version=DatabaseConstants.ENGINE_VERSION,
        instance_class=instance_class,
        allocated_storage=allocated_storage,
        db_name="edi_shard",
        username=DatabaseConstants.MASTER_USERNAME,
        password=edi_db_password.result,
        vpc_security_group_ids=[db_sg_id],
        db_subnet_group_name=db_subnet_group_name,
        parameter_group_name=edi_db_parameter_group.name,
        skip_final_snapshot=False,
        final_snapshot_identifier=f"{prefix}edi-shard-db-final-snapshot",
        publicly_accessible=False,
        tags=tags,
    )

    is_prod = pulumi.get_stack() == "production"

    edi_db_secret = aws.secretsmanager.Secret(
        f"{prefix}edi-shard-db-secret",
        name_prefix=f"edi/{prefix}edi-shard-db-credentials-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )

    aws.secretsmanager.SecretVersion(
        f"{prefix}edi-shard-db-secret-val",
        secret_id=edi_db_secret.id,
        secret_string=pulumi.Output.all(
            edi_shard_db.address, edi_shard_db.port, edi_db_password.result
        ).apply(
            lambda args: json.dumps(
                {
                    "host": args[0],
                    "port": args[1],
                    "username": DatabaseConstants.MASTER_USERNAME,
                    "password": args[2],
                    "dbname": "edi_shard",
                    "url": f"postgresql://{DatabaseConstants.MASTER_USERNAME}:{args[2]}@{args[0]}:{args[1]}/edi_shard",
                    "async_url": f"postgresql+asyncpg://{DatabaseConstants.MASTER_USERNAME}:{args[2]}@{args[0]}:{args[1]}/edi_shard",
                }
            )
        ),
    )

    return edi_shard_db, edi_db_secret
