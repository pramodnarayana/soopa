"""
Typed ECS Migrator Task Dispatcher
===================================
Triggers the dedicated ECS Migrator Task in AWS, applies command overrides
for domain-scoped migrations, streams CloudWatch logs, and asserts completion.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import boto3
import botocore.exceptions
import structlog

logger = structlog.get_logger(__name__)


def find_migrator_stack_dir() -> Path:
    """Dynamically search for the migrator Pulumi stack directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "infra" / "cloud" / "aws" / "apps" / "migrator"
        if candidate.exists():
            return candidate.resolve()
        candidate2 = parent / "apps" / "migrator"
        if candidate2.exists():
            return candidate2.resolve()
    raise FileNotFoundError("Could not locate infra/cloud/aws/apps/migrator directory")


def get_migrator_stack_outputs(env: str) -> dict[str, str | dict]:
    """Fetch outputs from the Pulumi migrator stack."""
    migrator_dir = find_migrator_stack_dir()

    pulumi_bin = shutil.which("pulumi")
    if not pulumi_bin:
        raise FileNotFoundError("Pulumi CLI binary not found in PATH")

    cmd = [pulumi_bin, "stack", "output", "--stack", env, "--json"]
    logger.info("fetching_migrator_stack_outputs", stack=env, dir=str(migrator_dir))

    result = subprocess.run(  # noqa: S603 - Executing trusted pulumi binary resolved via shutil.which
        cmd,
        cwd=str(migrator_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error(
            "failed_to_fetch_pulumi_outputs",
            error=result.stderr,
            stack=env,
        )
        raise RuntimeError(f"Pulumi stack output failed: {result.stderr}")

    return json.loads(result.stdout)


def stream_task_logs(
    logs_client,
    log_group: str,
    task_id: str,
) -> None:
    """Stream CloudWatch logs for the completed or running task."""
    stream_name = f"migrator/app/{task_id}"
    logger.info("fetching_cloudwatch_logs", log_group=log_group, stream=stream_name)

    try:
        try:
            response = logs_client.get_log_events(
                logGroupName=log_group,
                logStreamName=stream_name,
                startFromHead=True,
            )
            events = response.get("events", [])
        except logs_client.exceptions.ResourceNotFoundException:
            response = logs_client.filter_log_events(
                logGroupName=log_group,
                logStreamNamePrefix=stream_name,
            )
            events = response.get("events", [])

        for event in events:
            message = event.get("message", "").rstrip()
            logger.info("ecs_task_log", log_entry=message)
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as exc:
        logger.warning(
            "cloudwatch_log_stream_failed",
            log_group=log_group,
            error=str(exc),
        )


def run_migration_task(
    env: str,
    action: str = "migrate",
    domain: str = "all",
    region: str = "us-east-1",
) -> int:
    """
    Dispatch an ECS task with command overrides and wait for execution.
    Returns the container's exit code.
    """
    cluster = f"{env}-cluster"
    log_group = f"/ecs/{env}-migrator-migrator"

    outputs = get_migrator_stack_outputs(env)
    task_def_arn = str(outputs["task_definition_arn"])
    net_config_raw = outputs["cli_network_configuration"]
    net_config = json.loads(net_config_raw) if isinstance(net_config_raw, str) else net_config_raw

    command_override = [
        "python",
        "-m",
        "platform_migrator",
        action,
        "--domain",
        domain,
    ]

    logger.info(
        "dispatching_ecs_task",
        cluster=cluster,
        task_definition=task_def_arn,
        action=action,
        domain=domain,
        command=command_override,
    )

    ecs = boto3.client("ecs", region_name=region)
    logs = boto3.client("logs", region_name=region)

    response = ecs.run_task(
        cluster=cluster,
        taskDefinition=task_def_arn,
        launchType="FARGATE",
        networkConfiguration=net_config,
        overrides={
            "containerOverrides": [
                {
                    "name": "app",
                    "command": command_override,
                }
            ]
        },
    )

    tasks = response.get("tasks", [])
    failures = response.get("failures", [])

    if failures or not tasks:
        logger.error("ecs_run_task_failed", failures=failures)
        raise RuntimeError(f"ECS run_task failed: {failures}")

    task_arn = tasks[0]["taskArn"]
    task_id = task_arn.split("/")[-1]
    logger.info("ecs_task_started", task_arn=task_arn, task_id=task_id)

    logger.info("waiting_for_task_completion", task_arn=task_arn)
    waiter = ecs.get_waiter("tasks_stopped")
    try:
        waiter.wait(
            cluster=cluster,
            tasks=[task_arn],
            WaiterConfig={"Delay": 5, "MaxAttempts": 120},
        )
    except botocore.exceptions.WaiterError as exc:
        logger.error(
            "ecs_task_waiter_timed_out",
            task_arn=task_arn,
            error=str(exc),
        )

    desc_response = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
    described_tasks = desc_response.get("tasks", [])

    if not described_tasks:
        logger.error("task_not_found_on_describe", task_arn=task_arn)
        raise RuntimeError(f"Could not describe stopped task {task_arn}")

    containers = described_tasks[0].get("containers", [])
    app_containers = [c for c in containers if c.get("name") == "app"]
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

    stream_task_logs(logs, log_group, task_id)

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dispatch typed ECS database migration and seed tasks"
    )
    parser.add_argument(
        "--env",
        type=str,
        default=os.environ.get("TARGET_ENV", "staging"),
        help="Target environment (staging, production)",
    )
    parser.add_argument(
        "--action",
        type=str,
        default="migrate",
        choices=["migrate", "seed"],
        help="Action to run inside container",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default="all",
        help="Target domain (platform, edi, all, ucp, identity, notification)",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS Region",
    )

    args = parser.parse_args()

    exit_code = run_migration_task(
        env=args.env,
        action=args.action,
        domain=args.domain,
        region=args.region,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
