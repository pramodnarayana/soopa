"""
Generic One-Off ECS Task Dispatcher
===================================
A domain-agnostic utility for executing arbitrary one-off tasks (migrations,
seeders, backfills) against an AWS ECS cluster using Pulumi stack outputs.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, TypedDict

import boto3
import botocore.exceptions
import structlog

logger = structlog.get_logger(__name__)


class CloudWatchLogsEvent(TypedDict, total=False):
    timestamp: int
    message: str
    ingestionTime: int


class CloudWatchLogsClientProtocol(Protocol):
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


def get_stack_outputs(stack_dir: Path | str, env: str) -> dict[str, str]:
    """Retrieve JSON outputs from a Pulumi stack directory."""
    pulumi_bin = shutil.which("pulumi")
    if not pulumi_bin:
        raise FileNotFoundError("Pulumi CLI binary not found in PATH")

    resolved_dir = Path(stack_dir).resolve()
    if not resolved_dir.is_dir():
        raise FileNotFoundError(f"Pulumi stack directory does not exist: {resolved_dir}")

    cmd = [pulumi_bin, "stack", "output", "--stack", env, "--json"]
    result = subprocess.run(  # noqa: S603 - Dynamic pulumi CLI binary path resolved safely via shutil.which
        cmd,
        cwd=resolved_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def stream_task_logs(
    logs_client: CloudWatchLogsClientProtocol,
    log_group: str,
    task_id: str,
    container_name: str = "app",
    stream_prefix: str = "app",
    poll_interval: float = 2.0,
    max_retries: int = 5,
) -> None:
    """Stream CloudWatch logs for the ECS task."""
    logger.info("streaming_logs_start", log_group=log_group, task_id=task_id)

    stream_name: str | None = None
    for _ in range(max_retries):
        try:
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                logStreamNamePrefix=task_id,
            )
            events = response.get("events", [])
            if events:
                stream_name = f"{task_id}"
                break
        except botocore.exceptions.ClientError as exc:
            logger.info("cloudwatch_stream_not_ready", error=str(exc))
        time.sleep(poll_interval)

    if not stream_name:
        stream_name = f"{stream_prefix}/{container_name}/{task_id}"

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
            error=str(exc),
        )


def run_ecs_task(
    *,
    env: str,
    stack_dir: Path | str,
    command: Sequence[str],
    cluster: str | None = None,
    container_name: str = "app",
    region: str = "us-east-1",
) -> int:
    """
    Dispatch an arbitrary one-off ECS task with command overrides and wait for execution.
    Returns the container's exit code.
    """
    if not command:
        raise ValueError("Command cannot be empty")

    resolved_dir = Path(stack_dir).resolve()
    outputs = get_stack_outputs(resolved_dir, env=env)
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

    task_def_arn = str(outputs["task_definition_arn"])
    net_config_raw = outputs["cli_network_configuration"]
    net_config = json.loads(net_config_raw) if isinstance(net_config_raw, str) else net_config_raw

    task_family = outputs.get("task_definition_family") or task_def_arn.split("/")[-1].split(":")[0]
    log_group = outputs.get("log_group") or f"/ecs/{task_family}"
    resolved_cluster = cluster or f"{env}-cluster"

    command_list = list(command)

    logger.info(
        "dispatching_ecs_task",
        cluster=resolved_cluster,
        task_definition=task_def_arn,
        container=container_name,
        command=command_list,
    )

    ecs = boto3.client("ecs", region_name=region)
    logs = boto3.client("logs", region_name=region)

    response = ecs.run_task(
        cluster=resolved_cluster,
        taskDefinition=task_def_arn,
        launchType="FARGATE",
        networkConfiguration=net_config,
        overrides={
            "containerOverrides": [
                {
                    "name": container_name,
                    "command": command_list,
                }
            ]
        },
    )

    tasks = response.get("tasks", [])
    if not tasks:
        failures = response.get("failures", [])
        logger.error("ecs_run_task_failed", failures=failures)
        raise RuntimeError(f"Failed to run ECS task: {failures}")

    task_arn = tasks[0]["taskArn"]
    task_id = task_arn.split("/")[-1]
    logger.info("ecs_task_started", task_arn=task_arn, task_id=task_id)

    waiter = ecs.get_waiter("tasks_stopped")
    try:
        waiter.wait(
            cluster=resolved_cluster,
            tasks=[task_arn],
            WaiterConfig={"Delay": 5, "MaxAttempts": 60},
        )
    except botocore.exceptions.WaiterError as exc:
        logger.error("ecs_task_waiter_failed", task_arn=task_arn, error=str(exc))

    described = ecs.describe_tasks(cluster=resolved_cluster, tasks=[task_arn])
    described_tasks = described.get("tasks", [])
    if not described_tasks:
        logger.error("ecs_task_not_found_on_describe", task_arn=task_arn)
        raise RuntimeError(f"Could not describe stopped task {task_arn}")

    containers = described_tasks[0].get("containers", [])
    app_containers = [c for c in containers if c.get("name") == container_name]
    container = app_containers[0] if app_containers else (containers[0] if containers else {})

    raw_exit_code = container.get("exitCode")
    exit_code = 1 if raw_exit_code is None else int(raw_exit_code)
    stop_reason = described_tasks[0].get("stoppedReason", "Unknown")

    logger.info(
        "ecs_task_finished",
        task_arn=task_arn,
        exit_code=exit_code,
        stopped_reason=stop_reason,
    )

    stream_task_logs(
        logs,
        log_group,
        task_id,
        container_name=container_name,
        stream_prefix=outputs.get("log_stream_prefix") or "app",
    )

    return exit_code


def main() -> None:
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
        help="Command to execute inside the container (e.g. 'python -m platform_migrator migrate --domain platform')",
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

    args = parser.parse_args()

    command_args = shlex.split(args.command)
    exit_code = run_ecs_task(
        env=args.env,
        stack_dir=args.stack_dir,
        command=command_args,
        cluster=args.cluster,
        container_name=args.container_name,
        region=args.region,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
