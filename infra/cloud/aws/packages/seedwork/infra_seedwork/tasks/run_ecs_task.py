"""
Generic One-Off ECS Task Dispatcher
===================================
A domain-agnostic utility for executing arbitrary one-off tasks (migrations,
seeders, backfills) against an AWS ECS cluster using Pulumi stack outputs.
Follows Hexagonal Architecture and Dependency Inversion.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, TypedDict

import boto3
import botocore.exceptions
import structlog

logger = structlog.get_logger(__name__)


# ── Domain Ports (Protocols) ──────────────────────────────────────────────────


class CloudWatchLogsEvent(TypedDict, total=False):
    timestamp: int
    message: str
    ingestionTime: int


class LogsClientPort(Protocol):
    def get_log_events(
        self,
        *,
        logGroupName: str,
        logStreamName: str,
        startFromHead: bool = ...,
    ) -> Mapping[str, Sequence[CloudWatchLogsEvent]]: ...

    def filter_log_events(
        self,
        *,
        logGroupName: str,
        logStreamNamePrefix: str,
    ) -> Mapping[str, Sequence[CloudWatchLogsEvent]]: ...


class EcsWaiterPort(Protocol):
    def wait(
        self,
        *,
        cluster: str,
        tasks: Sequence[str],
        WaiterConfig: Mapping[str, int] = ...,
    ) -> None: ...


class EcsClientPort(Protocol):
    def list_tasks(
        self,
        *,
        cluster: str,
        family: str,
        desiredStatus: str,
    ) -> Mapping[str, Sequence[str]]: ...

    def describe_tasks(
        self,
        *,
        cluster: str,
        tasks: Sequence[str],
    ) -> Mapping[str, Sequence[Mapping[str, object]]]: ...

    def run_task(
        self,
        *,
        cluster: str,
        taskDefinition: str,
        launchType: str,
        networkConfiguration: Mapping[str, object],
        overrides: Mapping[str, object],
    ) -> Mapping[str, Sequence[Mapping[str, object]]]: ...

    def stop_task(
        self,
        *,
        cluster: str,
        task: str,
        reason: str,
    ) -> Mapping[str, object]: ...

    def get_waiter(self, waiter_name: str) -> EcsWaiterPort: ...


StackOutputReaderPort = Callable[[Path | str, str], Mapping[str, str]]
SleeperPort = Callable[[float], None]
BinaryLocatorPort = Callable[[str], str | None]
SubprocessRunnerPort = Callable[..., subprocess.CompletedProcess[str]]


# ── Adapters ──────────────────────────────────────────────────────────────────


def read_pulumi_stack_outputs(
    stack_dir: Path | str,
    env: str,
    *,
    which_fn: BinaryLocatorPort = shutil.which,
    subprocess_runner: SubprocessRunnerPort = subprocess.run,
) -> dict[str, str]:
    """Retrieve JSON outputs from a Pulumi stack directory using the CLI."""
    pulumi_bin = which_fn("pulumi")
    if not pulumi_bin:
        raise FileNotFoundError("Pulumi CLI binary not found in PATH")

    resolved_dir = Path(stack_dir).resolve()
    if not resolved_dir.is_dir():
        raise FileNotFoundError(f"Pulumi stack directory does not exist: {resolved_dir}")

    cmd = [pulumi_bin, "stack", "output", "--stack", env, "--json"]
    result = subprocess_runner(
        cmd,
        cwd=resolved_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# Retain get_stack_outputs alias for backward compatibility
get_stack_outputs = read_pulumi_stack_outputs


# ── Log Streaming Helper ──────────────────────────────────────────────────────


def stream_task_logs(
    logs_client: LogsClientPort,
    log_group: str,
    task_id: str,
    *,
    container_name: str = "app",
    stream_prefix: str = "migrator",
    poll_interval: float = 2.0,
    max_retries: int = 5,
    sleeper: SleeperPort = time.sleep,
) -> None:
    """Stream CloudWatch logs for the ECS task using injected sleeper and client."""
    logger.info("streaming_logs_start", log_group=log_group, task_id=task_id)

    stream_name = f"{stream_prefix}/{container_name}/{task_id}"
    for _ in range(max_retries):
        try:
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                logStreamNamePrefix=stream_name,
            )
            events = response.get("events", [])
            if events:
                break
        except botocore.exceptions.ClientError as exc:
            logger.info("cloudwatch_stream_not_ready", error=str(exc))
        sleeper(poll_interval)

    try:
        events_resp = logs_client.get_log_events(
            logGroupName=log_group,
            logStreamName=stream_name,
            startFromHead=True,
        )
        for event in events_resp.get("events", []):
            logger.info(
                "ecs_task_log",
                task_id=task_id,
                message=event.get("message", "").rstrip(),
            )
    except botocore.exceptions.ClientError as exc:
        logger.info(
            "cloudwatch_log_stream_failed",
            log_group=log_group,
            stream_name=stream_name,
            error=str(exc),
        )


# ── Domain Orchestrator ───────────────────────────────────────────────────────


class EcsTaskRunner:
    """Enterprise orchestrator for executing one-off ECS tasks via injected ports."""

    def __init__(
        self,
        *,
        ecs_client: EcsClientPort,
        logs_client: LogsClientPort,
        stack_output_reader: StackOutputReaderPort = read_pulumi_stack_outputs,
        sleeper: SleeperPort = time.sleep,
    ) -> None:
        self._ecs = ecs_client
        self._logs = logs_client
        self._output_reader = stack_output_reader
        self._sleeper = sleeper

    def run(
        self,
        *,
        env: str,
        stack_dir: Path | str,
        command: Sequence[str],
        cluster: str | None = None,
        container_name: str = "app",
    ) -> int:
        """Execute a one-off task with command overrides and return exit code."""
        if not command:
            raise ValueError("Command cannot be empty")

        resolved_dir = Path(stack_dir).resolve()
        outputs = self._output_reader(resolved_dir, env)
        self._validate_stack_outputs(outputs, resolved_dir, env)

        task_def_arn = str(outputs["task_definition_arn"])
        net_config_raw = outputs["cli_network_configuration"]
        net_config = (
            json.loads(net_config_raw) if isinstance(net_config_raw, str) else net_config_raw
        )

        task_family = (
            outputs.get("task_definition_family") or task_def_arn.split("/")[-1].split(":")[0]
        )
        log_group = outputs.get("log_group") or f"/ecs/{task_family}"
        stream_prefix = outputs.get("log_stream_prefix") or "migrator"
        resolved_cluster = cluster or f"{env}-cluster"

        self._check_no_active_tasks(resolved_cluster, task_family)

        logger.info(
            "dispatching_ecs_task",
            cluster=resolved_cluster,
            task_definition=task_def_arn,
            container=container_name,
            command=list(command),
        )

        task_arn = self._dispatch_task(
            cluster=resolved_cluster,
            task_definition=task_def_arn,
            container_name=container_name,
            command=list(command),
            net_config=net_config,
        )
        task_id = task_arn.split("/")[-1]

        timed_out = self._wait_for_task_completion(resolved_cluster, task_arn)
        task_record = self._describe_stopped_task(resolved_cluster, task_arn, timed_out)

        exit_code = self._extract_container_exit_code(task_record, container_name)
        stop_reason = str(task_record.get("stoppedReason", "Unknown"))

        logger.info(
            "ecs_task_finished",
            task_arn=task_arn,
            exit_code=exit_code,
            stopped_reason=stop_reason,
        )

        stream_task_logs(
            self._logs,
            log_group,
            task_id,
            container_name=container_name,
            stream_prefix=stream_prefix,
            sleeper=self._sleeper,
        )

        return exit_code

    def _validate_stack_outputs(
        self, outputs: Mapping[str, str], resolved_dir: Path, env: str
    ) -> None:
        for required_key in ("task_definition_arn", "cli_network_configuration"):
            if required_key not in outputs:
                logger.error(
                    "missing_stack_output",
                    missing_key=required_key,
                    stack_dir=str(resolved_dir),
                    env=env,
                )
                raise KeyError(
                    f"Required Pulumi output '{required_key}' missing from stack '{resolved_dir}'"
                )

    def _check_no_active_tasks(self, cluster: str, family: str) -> None:
        existing_tasks = self._ecs.list_tasks(
            cluster=cluster,
            family=family,
            desiredStatus="RUNNING",
        )
        task_arns = existing_tasks.get("taskArns", [])
        if not task_arns:
            return

        described = self._ecs.describe_tasks(cluster=cluster, tasks=task_arns)
        active = [
            t
            for t in described.get("tasks", [])
            if str(t.get("lastStatus")) in ("RUNNING", "PENDING", "STOPPING")
        ]
        if active:
            active_arn = str(active[0].get("taskArn", "unknown"))
            active_status = str(active[0].get("lastStatus", "RUNNING"))
            logger.error(
                "active_task_already_exists",
                cluster=cluster,
                family=family,
                active_task_arn=active_arn,
                status=active_status,
            )
            raise RuntimeError(
                f"Cannot dispatch task: an existing task for family '{family}' is currently {active_status} ({active_arn})"
            )

    def _dispatch_task(
        self,
        *,
        cluster: str,
        task_definition: str,
        container_name: str,
        command: Sequence[str],
        net_config: Mapping[str, object],
    ) -> str:
        response = self._ecs.run_task(
            cluster=cluster,
            taskDefinition=task_definition,
            launchType="FARGATE",
            networkConfiguration=net_config,
            overrides={
                "containerOverrides": [
                    {
                        "name": container_name,
                        "command": list(command),
                    }
                ]
            },
        )
        tasks = response.get("tasks", [])
        if not tasks:
            failures = response.get("failures", [])
            logger.error("ecs_run_task_failed", failures=failures)
            raise RuntimeError(f"Failed to run ECS task: {failures}")
        task_arn = str(tasks[0]["taskArn"])
        logger.info("ecs_task_started", task_arn=task_arn, task_id=task_arn.split("/")[-1])
        return task_arn

    def _wait_for_task_completion(self, cluster: str, task_arn: str) -> bool:
        waiter = self._ecs.get_waiter("tasks_stopped")
        try:
            waiter.wait(
                cluster=cluster,
                tasks=[task_arn],
                WaiterConfig={"Delay": 5, "MaxAttempts": 60},
            )
            return False
        except botocore.exceptions.WaiterError as exc:
            logger.error("ecs_task_waiter_failed", task_arn=task_arn, error=str(exc))
            if (
                "Max attempts exceeded" in str(exc)
                or getattr(exc, "reason", None) == "Max attempts exceeded"
            ):
                self._cancel_timed_out_task(waiter, cluster, task_arn)
                return True
            return False

    def _cancel_timed_out_task(self, waiter: EcsWaiterPort, cluster: str, task_arn: str) -> None:
        logger.warning(
            "ecs_task_waiter_timed_out_cancelling",
            task_arn=task_arn,
            cluster=cluster,
        )
        try:
            self._ecs.stop_task(
                cluster=cluster,
                task=task_arn,
                reason="Task timed out waiting for completion",
            )
        except botocore.exceptions.ClientError as stop_exc:
            logger.error("ecs_stop_task_failed", task_arn=task_arn, error=str(stop_exc))

        try:
            waiter.wait(
                cluster=cluster,
                tasks=[task_arn],
                WaiterConfig={"Delay": 5, "MaxAttempts": 6},
            )
        except botocore.exceptions.WaiterError as stop_wait_exc:
            logger.error(
                "ecs_task_stop_confirmation_failed",
                task_arn=task_arn,
                error=str(stop_wait_exc),
            )

    def _describe_stopped_task(
        self, cluster: str, task_arn: str, timed_out: bool
    ) -> Mapping[str, object]:
        described = self._ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
        described_tasks = described.get("tasks", [])
        if not described_tasks:
            logger.error("ecs_task_not_found_on_describe", task_arn=task_arn)
            raise RuntimeError(f"Could not describe stopped task {task_arn}")

        task_record = described_tasks[0]
        task_last_status = str(task_record.get("lastStatus"))
        if timed_out and task_last_status != "STOPPED":
            logger.error(
                "ecs_task_cleanup_unconfirmed",
                task_arn=task_arn,
                status=task_last_status,
            )
            raise RuntimeError(
                f"ECS task {task_arn} timed out and cleanup could not confirm it stopped (current status: {task_last_status})"
            )
        return task_record

    @staticmethod
    def _extract_container_exit_code(task_record: Mapping[str, object], container_name: str) -> int:
        containers_raw = task_record.get("containers", [])
        containers: Sequence[Mapping[str, object]] = (
            containers_raw if isinstance(containers_raw, Sequence) else []
        )
        app_containers = [c for c in containers if c.get("name") == container_name]
        container = app_containers[0] if app_containers else (containers[0] if containers else {})
        raw_exit_code = container.get("exitCode")
        return 1 if raw_exit_code is None else int(raw_exit_code)


# ── Composition Root / Application Factory ────────────────────────────────────


def create_default_runner(region: str = "us-east-1") -> EcsTaskRunner:
    """Assemble concrete AWS and system adapters for production execution."""
    ecs_client: EcsClientPort = boto3.client("ecs", region_name=region)
    logs_client: LogsClientPort = boto3.client("logs", region_name=region)
    return EcsTaskRunner(
        ecs_client=ecs_client,
        logs_client=logs_client,
        stack_output_reader=read_pulumi_stack_outputs,
        sleeper=time.sleep,
    )


def run_ecs_task(
    *,
    env: str,
    stack_dir: Path | str,
    command: Sequence[str],
    cluster: str | None = None,
    container_name: str = "app",
    region: str = "us-east-1",
    runner: EcsTaskRunner | None = None,
) -> int:
    """Facade for running a task, allowing optional DI override of the runner."""
    resolved_runner = runner or create_default_runner(region=region)
    return resolved_runner.run(
        env=env,
        stack_dir=stack_dir,
        command=command,
        cluster=cluster,
        container_name=container_name,
    )


# ── CLI Interface ─────────────────────────────────────────────────────────────


def main(
    cli_args: Sequence[str] | None = None,
    *,
    runner: EcsTaskRunner | None = None,
) -> None:
    """CLI entrypoint accepting explicit arguments and optional runner override."""
    parser = argparse.ArgumentParser(
        description="Dispatch generic one-off ECS Fargate tasks using Pulumi stack outputs"
    )
    parser.add_argument(
        "--env",
        type=str,
        default=os.environ.get("TARGET_ENV", "staging"),
        help="Target environment (staging, production)",
    )
    parser.add_argument(
        "--stack-dir",
        type=str,
        required=True,
        help="Path to the Pulumi stack directory containing task definition exports",
    )
    parser.add_argument(
        "--command",
        type=str,
        required=True,
        help="Command to execute inside the container (e.g. 'python -m package_name command --flag value')",
    )
    parser.add_argument(
        "--cluster",
        type=str,
        default=None,
        help="ECS Cluster name (defaults to {env}-cluster)",
    )
    parser.add_argument(
        "--container-name",
        type=str,
        default="app",
        help="Container name inside task definition (default: 'app')",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS Region",
    )

    args = parser.parse_args(cli_args)
    command_args = shlex.split(args.command)
    exit_code = run_ecs_task(
        env=args.env,
        stack_dir=args.stack_dir,
        command=command_args,
        cluster=args.cluster,
        container_name=args.container_name,
        region=args.region,
        runner=runner,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
