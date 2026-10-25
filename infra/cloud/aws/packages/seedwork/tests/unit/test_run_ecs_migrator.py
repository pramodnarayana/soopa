"""
Unit Tests for ECS Migrator Task Dispatcher
"""

import sys
from pathlib import Path

import botocore.exceptions
import pytest
from infra_seedwork.tasks.run_ecs_migrator import (
    find_migrator_stack_dir,
    get_migrator_stack_outputs,
    main,
    run_migration_task,
)


def test_find_migrator_stack_dir() -> None:
    platform_dir = find_migrator_stack_dir("platform")
    assert isinstance(platform_dir, Path)
    assert platform_dir.exists()
    assert (platform_dir / "__main__.py").exists()

    edi_dir = find_migrator_stack_dir("edi")
    assert isinstance(edi_dir, Path)
    assert edi_dir.exists()
    assert (edi_dir / "__main__.py").exists()


def test_get_migrator_stack_outputs_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    with pytest.raises(FileNotFoundError, match="Pulumi CLI binary not found in PATH"):
        get_migrator_stack_outputs("staging")


def test_run_migration_task_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-migrator:1",
        "cli_network_configuration": '{"awsvpcConfiguration": {"subnets": ["subnet-1"], "securityGroups": ["sg-1"]}}',
    }
    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.get_migrator_stack_outputs",
        lambda _env, **kwargs: fake_outputs,
    )

    class FakeLogsClient:
        def get_log_events(self, **kwargs):
            return {"events": [{"message": "all good"}]}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {
                "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123"}],
                "failures": [],
            }

        def get_waiter(self, waiter_name):
            return FakeWaiter()

        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123",
                        "containers": [{"exitCode": 0}],
                        "stoppedReason": "Essential container in task exited",
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    exit_code = run_migration_task(env="staging", action="migrate", domain="edi")
    assert exit_code == 0


def test_run_migration_task_selects_app_container(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-migrator:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.get_migrator_stack_outputs",
        lambda _env, **kwargs: fake_outputs,
    )

    class FakeLogsClient:
        def get_log_events(self, **kwargs):
            return {"events": [{"message": "app finished"}]}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name):
            return FakeWaiter()

        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:task/123",
                        "containers": [
                            {"name": "datadog-agent", "exitCode": 0},
                            {"name": "app", "exitCode": 42},
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    exit_code = run_migration_task(env="staging", action="migrate", domain="platform")
    assert exit_code == 42


def test_run_migration_task_waiter_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-migrator:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.get_migrator_stack_outputs",
        lambda _env, **kwargs: fake_outputs,
    )

    class FakeLogsClient:
        def get_log_events(self, **kwargs):
            return {"events": [{"message": "timeout logs"}]}

    class FakeTimeoutWaiter:
        def wait(self, **kwargs):
            raise botocore.exceptions.WaiterError(
                name="tasks_stopped", reason="Max attempts exceeded", last_response={}
            )

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name):
            return FakeTimeoutWaiter()

        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:task/123",
                        "containers": [{"name": "app", "exitCode": 137}],
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    exit_code = run_migration_task(env="staging", action="migrate", domain="platform")
    assert exit_code == 137


def test_run_migration_task_none_exit_code_defaults_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-migrator:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.get_migrator_stack_outputs",
        lambda _env, **kwargs: fake_outputs,
    )

    class FakeLogsClient:
        def get_log_events(self, **kwargs):
            return {"events": []}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name):
            return FakeWaiter()

        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:task/123",
                        "containers": [{"name": "app", "exitCode": None}],
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    exit_code = run_migration_task(env="staging", action="migrate", domain="platform")
    assert exit_code == 1


def test_main_cli_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ecs_migrator.py", "--env", "staging", "--action", "migrate", "--domain", "edi"],
    )
    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.run_migration_task",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert len(calls) == 1
    assert calls[0]["env"] == "staging"
    assert calls[0]["action"] == "migrate"
    assert calls[0]["domain"] == "edi"


def test_run_migration_task_seed_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-platform-migrator:1",
        "cli_network_configuration": '{"awsvpcConfiguration": {"subnets": ["subnet-1"], "securityGroups": ["sg-1"]}}',
    }
    stack_domain_queried = []

    def fake_get_outputs(env: str, domain: str = "platform") -> dict[str, str]:
        stack_domain_queried.append(domain)
        return fake_outputs

    monkeypatch.setattr(
        "infra_seedwork.tasks.run_ecs_migrator.get_migrator_stack_outputs",
        fake_get_outputs,
    )

    class FakeLogsClient:
        def get_log_events(self, **kwargs):
            return {"events": []}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    dispatched_commands = []

    class FakeEcsClient:
        def run_task(self, **kwargs):
            dispatched_commands.append(kwargs["overrides"]["containerOverrides"][0]["command"])
            return {
                "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123"}],
                "failures": [],
            }

        def get_waiter(self, waiter_name: str):
            return FakeWaiter()

        def describe_tasks(self, **kwargs):
            return {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:task/123",
                        "containers": [{"name": "app", "exitCode": 0}],
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    # Seed action for edi must use the platform stack and invoke platform_migrator seed --domain edi
    exit_code = run_migration_task(env="staging", action="seed", domain="edi")
    assert exit_code == 0
    assert stack_domain_queried == ["platform"]
    assert dispatched_commands == [["python", "-m", "platform_migrator", "seed", "--domain", "edi"]]
