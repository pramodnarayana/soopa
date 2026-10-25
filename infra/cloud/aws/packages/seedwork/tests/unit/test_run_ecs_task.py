"""
Unit Tests for Generic ECS Task Dispatcher
==========================================
Tests written with 100% pure dependency injection and in-memory test doubles.
Zero monkeypatching, adhering strictly to enterprise Hexagonal Architecture.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import botocore.exceptions
import pytest
from infra_seedwork.tasks.run_ecs_task import (
    CloudWatchLogsEvent,
    EcsTaskRunner,
    EcsWaiterPort,
    main,
    read_pulumi_stack_outputs,
    run_ecs_task,
)

# ── In-Memory Fakes (Test Doubles) ───────────────────────────────────────────


class FakeLogsClient:
    def __init__(self, events: Sequence[CloudWatchLogsEvent] | None = None) -> None:
        self.events: Sequence[CloudWatchLogsEvent] = events or []
        self.filter_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def filter_log_events(
        self,
        *,
        logGroupName: str,
        logStreamNamePrefix: str,
    ) -> Mapping[str, Sequence[CloudWatchLogsEvent]]:
        self.filter_calls.append(
            {"logGroupName": logGroupName, "logStreamNamePrefix": logStreamNamePrefix}
        )
        return {"events": self.events}

    def get_log_events(
        self,
        *,
        logGroupName: str,
        logStreamName: str,
        startFromHead: bool = True,
    ) -> Mapping[str, Sequence[CloudWatchLogsEvent]]:
        self.get_calls.append(
            {
                "logGroupName": logGroupName,
                "logStreamName": logStreamName,
                "startFromHead": startFromHead,
            }
        )
        return {"events": self.events}


class FakeWaiter:
    def __init__(self, should_timeout: bool = False) -> None:
        self.should_timeout = should_timeout
        self.wait_calls: list[dict[str, object]] = []

    def wait(
        self,
        *,
        cluster: str,
        tasks: Sequence[str],
        WaiterConfig: Mapping[str, int] = ...,
    ) -> None:
        self.wait_calls.append({"cluster": cluster, "tasks": tasks, "WaiterConfig": WaiterConfig})
        if self.should_timeout:
            raise botocore.exceptions.WaiterError(
                name="tasks_stopped",
                reason="Max attempts exceeded",
                last_response={},
            )


class FakeEcsClient:
    def __init__(
        self,
        *,
        active_tasks: Sequence[str] | None = None,
        exit_code: int | None = 0,
        waiter: EcsWaiterPort | None = None,
        last_status: str = "STOPPED",
        app_container_name: str = "app",
    ) -> None:
        self.active_tasks = list(active_tasks or [])
        self.exit_code = exit_code
        self.waiter = waiter or FakeWaiter()
        self.last_status = last_status
        self.app_container_name = app_container_name
        self.dispatched_tasks: list[dict[str, object]] = []
        self.stopped_tasks: list[dict[str, object]] = []

    def list_tasks(
        self,
        *,
        cluster: str,
        family: str,
        desiredStatus: str,
    ) -> Mapping[str, Sequence[str]]:
        return {"taskArns": self.active_tasks}

    def describe_tasks(
        self,
        *,
        cluster: str,
        tasks: Sequence[str],
    ) -> Mapping[str, Sequence[Mapping[str, object]]]:
        return {
            "tasks": [
                {
                    "taskArn": task,
                    "lastStatus": self.last_status,
                    "containers": [{"name": self.app_container_name, "exitCode": self.exit_code}],
                    "stoppedReason": "Task completed successfully",
                }
                for task in tasks
            ]
        }

    def run_task(
        self,
        *,
        cluster: str,
        taskDefinition: str,
        launchType: str,
        networkConfiguration: Mapping[str, object],
        overrides: Mapping[str, object],
    ) -> Mapping[str, Sequence[Mapping[str, object]]]:
        self.dispatched_tasks.append(
            {
                "cluster": cluster,
                "taskDefinition": taskDefinition,
                "networkConfiguration": networkConfiguration,
                "overrides": overrides,
            }
        )
        return {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123",
                }
            ],
            "failures": [],
        }

    def stop_task(
        self,
        *,
        cluster: str,
        task: str,
        reason: str,
    ) -> Mapping[str, object]:
        self.stopped_tasks.append({"cluster": cluster, "task": task, "reason": reason})
        return {"task": {"taskArn": task}}

    def get_waiter(self, waiter_name: str) -> EcsWaiterPort:
        return self.waiter


# ── Stack Output Tests (Pure Dependency Injection) ───────────────────────────


def test_read_stack_outputs_missing_binary(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Pulumi CLI binary not found in PATH"):
        read_pulumi_stack_outputs(tmp_path, env="staging", which_fn=lambda _bin: None)


def test_read_stack_outputs_missing_dir(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError, match="Pulumi stack directory does not exist"):
        read_pulumi_stack_outputs(
            non_existent,
            env="staging",
            which_fn=lambda _bin: "/usr/local/bin/pulumi",
        )


# ── Runner Unit Tests (Pure Dependency Injection, Zero Monkeypatch) ───────────


def test_run_ecs_task_empty_command(tmp_path: Path) -> None:
    runner = EcsTaskRunner(
        ecs_client=FakeEcsClient(),
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: {},
        sleeper=lambda _: None,
    )
    with pytest.raises(ValueError, match="Command cannot be empty"):
        runner.run(env="staging", stack_dir=tmp_path, command=[])


def test_run_ecs_task_missing_output_key(tmp_path: Path) -> None:
    runner = EcsTaskRunner(
        ecs_client=FakeEcsClient(),
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: {"task_definition_arn": "arn:aws:ecs:..."},
        sleeper=lambda _: None,
    )
    with pytest.raises(KeyError, match="cli_network_configuration"):
        runner.run(env="staging", stack_dir=tmp_path, command=["echo", "hello"])


def test_run_ecs_task_rejects_active_task(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_family": "staging-platform-migrator",
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-platform-migrator:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(active_tasks=["arn:aws:ecs:task/active-1"], last_status="RUNNING")
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    with pytest.raises(
        RuntimeError,
        match="Cannot dispatch task: an existing task for family 'staging-platform-migrator' is currently RUNNING",
    ):
        runner.run(env="staging", stack_dir=tmp_path, command=["echo", "test"])


def test_run_ecs_task_dispatch(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_family": "staging-platform-migrator",
        "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/staging-platform-migrator:1",
        "cli_network_configuration": '{"awsvpcConfiguration": {"subnets": ["subnet-1"]}}',
        "log_group": "/ecs/custom-group",
        "log_stream_prefix": "migrator",
    }
    ecs = FakeEcsClient(exit_code=0)
    logs = FakeLogsClient(events=[{"message": "migration completed"}])

    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=logs,
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    command = ["python", "-m", "platform_migrator", "migrate", "--domain", "platform"]
    exit_code = runner.run(env="staging", stack_dir=tmp_path, command=command)

    assert exit_code == 0
    assert len(ecs.dispatched_tasks) == 1
    call = ecs.dispatched_tasks[0]
    assert call["cluster"] == "staging-cluster"
    assert call["taskDefinition"] == fake_outputs["task_definition_arn"]
    assert len(logs.filter_calls) == 1
    assert logs.filter_calls[0]["logStreamNamePrefix"] == "migrator/app/task-123"


def test_run_ecs_task_selects_app_container(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }

    class MultiContainerEcsClient(FakeEcsClient):
        def describe_tasks(
            self, *, cluster: str, tasks: Sequence[str]
        ) -> Mapping[str, Sequence[Mapping[str, object]]]:
            return {
                "tasks": [
                    {
                        "taskArn": tasks[0],
                        "lastStatus": "STOPPED",
                        "containers": [
                            {"name": "sidecar", "exitCode": 0},
                            {"name": "app", "exitCode": 42},
                        ],
                        "stoppedReason": "Completed",
                    }
                ]
            }

    runner = EcsTaskRunner(
        ecs_client=MultiContainerEcsClient(),
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    exit_code = runner.run(env="staging", stack_dir=tmp_path, command=["python", "test.py"])
    assert exit_code == 42


def test_run_ecs_task_waiter_timeout(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(
        exit_code=137,
        waiter=FakeWaiter(should_timeout=True),
        last_status="STOPPED",
    )
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    exit_code = runner.run(env="staging", stack_dir=tmp_path, command=["python", "test.py"])
    assert exit_code == 137
    assert len(ecs.stopped_tasks) == 1
    assert (
        ecs.stopped_tasks[0]["task"] == "arn:aws:ecs:us-east-1:123456789012:task/cluster/task-123"
    )


def test_run_ecs_task_unconfirmed_cleanup_raises(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(
        exit_code=137,
        waiter=FakeWaiter(should_timeout=True),
        last_status="STOPPING",
    )
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    with pytest.raises(RuntimeError, match="timed out and cleanup could not confirm it stopped"):
        runner.run(env="staging", stack_dir=tmp_path, command=["python", "test.py"])


def test_run_ecs_task_none_exit_code_defaults_to_one(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(exit_code=None, last_status="STOPPED")
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    exit_code = runner.run(env="staging", stack_dir=tmp_path, command=["python", "test.py"])
    assert exit_code == 1


def test_run_ecs_task_facade_injection(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(exit_code=0)
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    exit_code = run_ecs_task(
        env="staging",
        stack_dir=tmp_path,
        command=["python", "test.py"],
        runner=runner,
    )
    assert exit_code == 0


def test_main_cli_with_runner_injection(tmp_path: Path) -> None:
    fake_outputs = {
        "task_definition_arn": "arn:aws:ecs:task-def:1",
        "cli_network_configuration": "{}",
    }
    ecs = FakeEcsClient(exit_code=0)
    runner = EcsTaskRunner(
        ecs_client=ecs,
        logs_client=FakeLogsClient(),
        stack_output_reader=lambda _dir, _env: fake_outputs,
        sleeper=lambda _: None,
    )

    cli_args = [
        "--env",
        "staging",
        "--stack-dir",
        str(tmp_path),
        "--command",
        "python -m platform_migrator migrate --domain platform",
    ]

    with pytest.raises(SystemExit) as exc_info:
        main(cli_args, runner=runner)

    assert exc_info.value.code == 0
    assert len(ecs.dispatched_tasks) == 1
