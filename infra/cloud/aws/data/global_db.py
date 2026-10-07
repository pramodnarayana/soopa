import json
import urllib.parse

import pulumi
import pulumi_aws as aws
import pulumi_random as random
from constants import DatabaseConstants


def provision_global_db(
    prefix: str,
    db_subnet_group_name: str,
    db_sg_id: str,
    tags: dict,
    instance_class: str,
    allocated_storage: int,
):
    db_password = random.RandomPassword(
        "global-db-password",
        length=32,
        override_special="!#*_-=",
    )

    global_db_parameter_group = aws.rds.ParameterGroup(
        f"{prefix}global-db-pg",
        family="postgres15",
        parameters=[
            aws.rds.ParameterGroupParameterArgs(
                name="idle_in_transaction_session_timeout",
                value="300000",
                apply_method="immediate",
            ),
        ],
        tags=tags,
    )

    global_db = aws.rds.Instance(
        f"{prefix}global-db",
        identifier=f"{prefix}global-db",
        engine=DatabaseConstants.ENGINE,
        engine_version=DatabaseConstants.ENGINE_VERSION,
        instance_class=instance_class,
        allocated_storage=allocated_storage,
        db_name=DatabaseConstants.GLOBAL_DB_NAME,
        username=DatabaseConstants.MASTER_USERNAME,
        password=db_password.result,
        vpc_security_group_ids=[db_sg_id],
        db_subnet_group_name=db_subnet_group_name,
        parameter_group_name=global_db_parameter_group.name,
        skip_final_snapshot=False,
        final_snapshot_identifier=f"{prefix}global-db-final-snapshot",
        publicly_accessible=False,
        storage_encrypted=True,
        tags=tags,
    )

    is_prod = pulumi.get_stack() == "production"

    db_secret = aws.secretsmanager.Secret(
        f"{prefix}global-db-secret",
        name_prefix=f"edi/{prefix}global-db-credentials-",
        recovery_window_in_days=30 if is_prod else 0,
        tags=tags,
    )
    aws.secretsmanager.SecretVersion(
        f"{prefix}global-db-secret-val",
        secret_id=db_secret.id,
        secret_string=pulumi.Output.all(
            global_db.address, global_db.port, db_password.result
        ).apply(
            lambda args: json.dumps(
                {
                    "host": args[0],
                    "port": args[1],
                    "username": DatabaseConstants.MASTER_USERNAME,
                    "password": args[2],
                    "dbname": DatabaseConstants.GLOBAL_DB_NAME,
                    "url": f"postgresql://{DatabaseConstants.MASTER_USERNAME}:{urllib.parse.quote(args[2], safe='')}@{args[0]}:{args[1]}/{DatabaseConstants.GLOBAL_DB_NAME}",
                    "async_url": f"postgresql+asyncpg://{DatabaseConstants.MASTER_USERNAME}:{urllib.parse.quote(args[2], safe='')}@{args[0]}:{args[1]}/{DatabaseConstants.GLOBAL_DB_NAME}",
                }
            )
        ),
    )

    return global_db, db_secret, db_password
