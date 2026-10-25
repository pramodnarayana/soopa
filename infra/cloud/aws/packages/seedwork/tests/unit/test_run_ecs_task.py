"""
Unit Tests for Generic ECS Task Dispatcher
"""

import sys
from pathlib import Path

import botocore.exceptions
import infra_seedwork.tasks.run_ecs_task as run_ecs_task_module
import pytest
from infra_seedwork.tasks.run_ecs_task import (
    get_stack_outputs,
    main,
    run_ecs_task,
)


def test_get_stack_outputs_missing_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda _bin: None)
    with pytest.raises(FileNotFoundError, match="Pulumi CLI binary not found in PATH"):
        get_stack_outputs(tmp_path, env="staging")


def test_get_stack_outputs_missing_dir(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError, match="Pulumi stack directory does not exist"):
        get_stack_outputs(non_existent, env="staging")


def test_run_ecs_task_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Command cannot be empty"):
        run_ecs_task(env="staging", stack_dir=tmp_path, command=[])


def test_run_ecs_task_missing_output_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        run_ecs_task_module,
        "get_stack_outputs",
        lambda _dir, env: {"task_definition_arn": "arn:aws:ecs:..."},
    )
    with pytest.raises(KeyError, match="cli_network_configuration"):
        run_ecs_task(env="staging", stack_dir=tmp_path, command=["echo", "hello"])


def test_run_ecs_task_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_family": "staging-platform-migrator",
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-platform-migrator:1",
        "cli_network_configuration": '{"awsvpcConfiguration": {"subnets": ["subnet-1"], "securityGroups": ["sg-1"]}}',
    }
    queried_dirs: list[Path] = []

    def fake_get_outputs(stack_dir: Path | str, env: str) -> dict[str, str]:
        queried_dirs.append(Path(stack_dir))
        return fake_outputs

    monkeypatch.setattr(
        run_ecs_task_module,
        "get_stack_outputs",
        fake_get_outputs,
    )

    class FakeLogsClient:
        def filter_log_events(self, **kwargs):
            return {"events": [{"message": "ready"}]}

        def get_log_events(self, **kwargs):
            return {"events": [{"message": "migration completed successfully"}]}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    dispatched_tasks: list[dict] = []

    class FakeEcsClient:
        def run_task(self, **kwargs):
            dispatched_tasks.append(kwargs)
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
                        "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123",
                        "containers": [{"name": "app", "exitCode": 0}],
                        "stoppedReason": "Essential container in task exited",
                    }
                ]
            }

    monkeypatch.setattr(
        "boto3.client",
        lambda service, **kwargs: FakeEcsClient() if service == "ecs" else FakeLogsClient(),
    )

    command = ["python", "-m", "platform_migrator", "migrate", "--domain", "platform"]
    exit_code = run_ecs_task(
        env="staging",
        stack_dir=tmp_path,
        command=command,
    )

    assert exit_code == 0
    assert queried_dirs == [tmp_path]
    assert len(dispatched_tasks) == 1
    call = dispatched_tasks[0]
    assert call["cluster"] == "staging-cluster"
    assert call["taskDefinition"] == fake_outputs["task_definition_arn"]
    assert call["overrides"]["containerOverrides"][0]["command"] == command


def test_run_ecs_task_selects_app_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-task:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        run_ecs_task_module,
        "get_stack_outputs",
        lambda _dir, env: fake_outputs,
    )

    class FakeLogsClient:
        def filter_log_events(self, **kwargs):
            return {"events": []}

        def get_log_events(self, **kwargs):
            return {"events": []}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name: str):
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

    exit_code = run_ecs_task(
        env="staging",
        stack_dir=tmp_path,
        command=["python", "test.py"],
    )
    assert exit_code == 42


def test_run_ecs_task_waiter_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-task:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        run_ecs_task_module,
        "get_stack_outputs",
        lambda _dir, env: fake_outputs,
    )

    class FakeLogsClient:
        def filter_log_events(self, **kwargs):
            return {"events": []}

        def get_log_events(self, **kwargs):
            return {"events": []}

    class FakeTimeoutWaiter:
        def wait(self, **kwargs):
            raise botocore.exceptions.WaiterError(
                name="tasks_stopped", reason="Max attempts exceeded", last_response={}
            )

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name: str):
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

    exit_code = run_ecs_task(
        env="staging",
        stack_dir=tmp_path,
        command=["python", "test.py"],
    )
    assert exit_code == 137


def test_run_ecs_task_none_exit_code_defaults_to_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-task:1",
        "cli_network_configuration": "{}",
    }
    monkeypatch.setattr(
        run_ecs_task_module,
        "get_stack_outputs",
        lambda _dir, env: fake_outputs,
    )

    class FakeLogsClient:
        def filter_log_events(self, **kwargs):
            return {"events": []}

        def get_log_events(self, **kwargs):
            return {"events": []}

    class FakeWaiter:
        def wait(self, **kwargs):
            pass

    class FakeEcsClient:
        def run_task(self, **kwargs):
            return {"tasks": [{"taskArn": "arn:aws:ecs:task/123"}], "failures": []}

        def get_waiter(self, waiter_name: str):
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

    exit_code = run_ecs_task(
        env="staging",
        stack_dir=tmp_path,
        command=["python", "test.py"],
    )
    assert exit_code == 1


def test_main_cli_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ecs_task.py",
            "--env",
            "staging",
            "--stack-dir",
            str(tmp_path),
            "--command",
            "python -m platform_migrator migrate --domain platform",
        ],
    )
    monkeypatch.setattr(
        run_ecs_task_module,
        "run_ecs_task",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert len(calls) == 1
    assert calls[0]["env"] == "staging"
    assert calls[0]["stack_dir"] == str(tmp_path)
    assert calls[0]["command"] == [
        "python",
        "-m",
        "platform_migrator",
        "migrate",
        "--domain",
        "platform",
    ]
