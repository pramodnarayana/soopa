"""Pure unit tests for Fargate ECS primitives and builders (Zero Mocks)."""

from infra_seedwork.ecs import (
    EcsConstants,
    ObservabilityConstants,
    build_awslogs_log_config,
    build_container_definitions,
    build_firelens_log_config,
    build_firelens_sidecar,
    build_task_role_policy_statements,
)


def test_build_container_definitions_injects_command_and_metadata():
    """Verify that pure container definition builder attaches entrypoint command and metadata."""
    containers = build_container_definitions(
        name="test-worker",
        image="123456789012.dkr.ecr.us-east-1.amazonaws.com/modular-monolith:latest",
        command=["python", "-m", "apps.test.worker"],
        port_mappings=[{"containerPort": 8080, "hostPort": 8080}],
        environment=[{"name": "ENV", "value": "test"}],
        secrets=[{"name": "DB_PASS", "valueFrom": "arn:aws:secretsmanager:..."}],
    )

    assert len(containers) == 1
    app_container = containers[0]
    assert app_container["name"] == EcsConstants.CONTAINER_NAME_APP
    assert app_container["command"] == ["python", "-m", "apps.test.worker"]
    assert (
        app_container["image"]
        == "123456789012.dkr.ecr.us-east-1.amazonaws.com/modular-monolith:latest"
    )
    assert app_container["essential"] is True
    assert app_container["portMappings"] == [{"containerPort": 8080, "hostPort": 8080}]
    assert app_container["environment"] == [{"name": "ENV", "value": "test"}]
    assert app_container["secrets"] == [
        {"name": "DB_PASS", "valueFrom": "arn:aws:secretsmanager:..."}
    ]


def test_build_container_definitions_appends_sidecars():
    """Verify that sidecar containers (e.g. FluentBit) are appended cleanly."""
    sidecar = build_firelens_sidecar(
        group_name="/ecs/test-worker",
        region_name="us-east-1",
    )
    containers = build_container_definitions(
        name="test-worker",
        image="app-image:latest",
        command=["python", "worker.py"],
        sidecars=[sidecar],
    )

    assert len(containers) == 2
    assert containers[0]["name"] == EcsConstants.CONTAINER_NAME_APP
    assert containers[1]["name"] == EcsConstants.CONTAINER_NAME_LOG_ROUTER
    assert containers[1]["image"] == ObservabilityConstants.DEFAULT_FLUENTBIT_IMAGE
    assert containers[1]["essential"] is True


def test_build_awslogs_log_config_structure():
    """Verify CloudWatch awslogs configuration schema."""
    config = build_awslogs_log_config(
        group_name="/ecs/api",
        region_name="us-east-1",
        stream_prefix="api",
    )
    assert config["logDriver"] == EcsConstants.LOG_DRIVER_AWSLOGS
    assert config["options"]["awslogs-group"] == "/ecs/api"
    assert config["options"]["awslogs-region"] == "us-east-1"
    assert config["options"]["awslogs-stream-prefix"] == "api"
    assert config["options"]["awslogs-create-group"] == "true"


def test_build_firelens_log_config_with_secrets():
    """Verify Firelens log configuration with OpenObserve credentials."""
    config = build_firelens_log_config(
        fl_end="openobserve.internal:5080",
        obs_user_arn="arn:aws:secretsmanager:us-east-1:123:secret:obs-user",
        obs_pass_arn="arn:aws:secretsmanager:us-east-1:123:secret:obs-pass",
    )
    assert config["logDriver"] == EcsConstants.LOG_DRIVER_FIRELENS
    assert config["options"]["Host"] == "openobserve.internal"
    assert config["options"]["Port"] == "5080"
    assert config["secretOptions"] == [
        {
            "name": "http_user",
            "valueFrom": "arn:aws:secretsmanager:us-east-1:123:secret:obs-user",
        },
        {
            "name": "http_passwd",
            "valueFrom": "arn:aws:secretsmanager:us-east-1:123:secret:obs-pass",
        },
    ]


def test_build_task_role_policy_statements_composition():
    """Verify pure IAM policy statement assembly for queues, topics, buckets, and SSM."""
    statements = build_task_role_policy_statements(
        queue_arns=["arn:aws:sqs:us-east-1:123:my-queue"],
        topic_arns=["arn:aws:sns:us-east-1:123:my-topic"],
        bucket_arns=["arn:aws:s3:::my-bucket"],
        extra_statements=[{"Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": "*"}],
        enable_execute_command=True,
    )

    actions = [s["Action"] for s in statements]
    assert ["sqs:*"] in actions
    assert ["sns:*"] in actions
    assert ["s3:*"] in actions
    assert ["kms:Decrypt"] in actions
    sids = [s.get("Sid") for s in statements]
    assert "ExecuteCommand" in sids
