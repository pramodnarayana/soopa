"""Pure unit tests for Fargate ECS primitives and builders (Zero Mocks)."""

from infra_seedwork.ecs import (
    EcsConstants,
    ObservabilityConstants,
    _build_service_sidecars,
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


def test_build_container_definitions_omits_log_configuration_when_empty():
    """Verify that logConfiguration is omitted from container def when not supplied or empty."""
    containers_none = build_container_definitions(
        name="test-worker",
        image="app-image:latest",
        log_configuration=None,
    )
    assert "logConfiguration" not in containers_none[0]

    containers_empty = build_container_definitions(
        name="test-worker",
        image="app-image:latest",
        log_configuration={},
    )
    assert "logConfiguration" not in containers_empty[0]


def test_build_container_definitions_preserves_supplied_log_configuration():
    """Verify that supplied logConfiguration is preserved on container definition."""
    log_config = build_awslogs_log_config(
        group_name="/ecs/test",
        region_name="us-east-1",
    )
    containers = build_container_definitions(
        name="test-worker",
        image="app-image:latest",
        log_configuration=log_config,
    )
    assert "logConfiguration" in containers[0]
    assert containers[0]["logConfiguration"]["logDriver"] == EcsConstants.LOG_DRIVER_AWSLOGS


def test_build_container_definitions_custom_sidecar_defaults_essential_and_preserves_fields():
    """Verify that a custom sidecar preserves ECS fields (command, healthCheck) and defaults essential to True."""
    sidecar = {
        "name": "custom-agent",
        "command": ["./agent", "--port", "9090"],
        "healthCheck": {
            "command": ["CMD-SHELL", "curl -f http://localhost:9090/health || exit 1"],
            "interval": 30,
            "timeout": 5,
        },
        "user": "1001:1001",
    }
    containers = build_container_definitions(
        name="test-app",
        image="main-app:latest",
        sidecars=[sidecar],
    )
    assert len(containers) == 2
    sidecar_def = containers[1]
    assert sidecar_def["name"] == "custom-agent"
    assert sidecar_def["image"] == "main-app:latest"  # fallback to main image
    assert sidecar_def["essential"] is True  # defaults to True
    assert sidecar_def["command"] == ["./agent", "--port", "9090"]
    assert sidecar_def["healthCheck"] == {
        "command": ["CMD-SHELL", "curl -f http://localhost:9090/health || exit 1"],
        "interval": 30,
        "timeout": 5,
    }
    assert sidecar_def["user"] == "1001:1001"


def test_build_container_definitions_custom_sidecar_respects_explicit_essential_false():
    """Verify that a custom sidecar preserves explicit essential=False."""
    sidecar = {
        "name": "optional-metrics",
        "essential": False,
        "image": "prom/statsd-exporter:latest",
    }
    containers = build_container_definitions(
        name="test-app",
        image="main-app:latest",
        sidecars=[sidecar],
    )
    assert len(containers) == 2
    sidecar_def = containers[1]
    assert sidecar_def["essential"] is False
    assert sidecar_def["image"] == "prom/statsd-exporter:latest"


def test_build_service_sidecars_preserves_missing_image_key():
    """Verify that _build_service_sidecars does not inject image: None when image is omitted."""
    sidecars = _build_service_sidecars(
        name="api",
        region_name="us-east-1",
        firelens_endpoint=None,
        fluentbit_image_uri=ObservabilityConstants.DEFAULT_FLUENTBIT_IMAGE,
        sidecar_container={"name": "sidecar-worker"},
    )
    assert len(sidecars) == 1
    assert "image" not in sidecars[0]
