import json
import os
import sys

import pulumi
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packages")))
from seedwork.ecs import provision_fargate_service

captured_task_defs = []


class MyMocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        outputs = dict(args.inputs)
        if args.typ == "aws:ecs/taskDefinition:TaskDefinition":
            captured_task_defs.append(args.inputs)
            outputs["arn"] = f"arn:aws:ecs:us-east-1:123456789012:task-definition/{args.name}:1"
        return [f"{args.name}-id", outputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        if args.token == "aws:index/getCallerIdentity:getCallerIdentity":
            return {
                "accountId": "123456789012",
                "arn": "arn:aws:iam::123456789012:root",
                "userId": "AKIAIOSFODNN7EXAMPLE",
            }
        if args.token == "aws:index/getRegion:getRegion":
            return {"name": "us-east-1"}
        return {}


@pytest.fixture(scope="function", autouse=True)
def override_mocks():
    pulumi.runtime.set_mocks(MyMocks())
    captured_task_defs.clear()


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
        # The captured_task_defs list should have the task definition inputs
        assert len(captured_task_defs) > 0
        task_definition_args = captured_task_defs[0]
        container_definitions = task_definition_args.get("containerDefinitions")

        if isinstance(container_definitions, str):
            containers = json.loads(container_definitions)
            command = containers[0].get("command", [])
            assert command == ["python", "-m", "apps.test.worker"], f"Command mismatch: {command}"

    # Verify that the task definition is correctly wired up
    pulumi.Output.all(service_result.task_definition).apply(check_task_def)
