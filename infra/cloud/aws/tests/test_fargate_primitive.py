import json

import pulumi
import pytest

# Import the custom primitive from the local packages
from packages.seedwork.ecs import provision_fargate_service


@pytest.mark.asyncio(loop_scope="function")
async def test_provision_fargate_service_injects_command():
    """
    Test that the provision_fargate_service injects the entrypoint command.
    """
    service_result = provision_fargate_service(
        name="test-worker",
        command=["python", "-m", "apps.test.worker"],
        cluster_arn="arn:aws:ecs:us-east-1:123456789012:cluster/test-cluster",
        subnets=["subnet-123", "subnet-456"],
        security_group_id="sg-123",
        ecr_image_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/modular-monolith:latest",
        execution_role_arn="arn:aws:iam::123456789012:role/ExecRole",
        tags={"Environment": "Test"},
    )

    # Wait for the service to be created and check the task definition
    def check_task_def(args):
        task_definition_args = args[0]
        container_definitions = task_definition_args.get("containerDefinitions")

        if isinstance(container_definitions, str):
            containers = json.loads(container_definitions)
            command = containers[0].get("command", [])
            assert command == ["python", "-m", "apps.test.worker"], f"Command mismatch: {command}"

    # Verify that the task definition is correctly wired up
    pulumi.Output.all(service_result.task_definition).apply(check_task_def)
