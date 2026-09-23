# ruff: noqa: G004
import json
import re
import sys

import structlog

logger = structlog.get_logger(__name__)
from pathlib import Path


def main():
    logger.info("Syncing Topology configuration to .env...")

    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent.parent
    env_path = root_dir / ".env"
    topology_path = root_dir / "infra" / "topology.json"

    if not topology_path.exists():
        logger.error(f"ERROR: topology.json not found at {topology_path}")
        sys.exit(1)

    if not env_path.exists():
        logger.error(f"ERROR: .env file not found at {env_path}")
        sys.exit(1)

    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    env_content = env_path.read_text(encoding="utf-8")

    LOCALSTACK_URL = "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/"
    LOCALSTACK_SNS_ARN = "arn:aws:sns:us-east-1:000000000000:"

    mappings = {}

    # Process Queues
    for queue in topology.get("queues", []):
        name = queue["name"]
        is_fifo = queue.get("fifo", False)

        physical_name = f"{name}.fifo" if is_fifo else name
        env_var_name = queue.get("env_var", f"SQS_{name.upper().replace('-', '_')}_QUEUE_URL")
        mappings[env_var_name] = f"{LOCALSTACK_URL}{physical_name}"

    # Process Topics
    for topic in topology.get("topics", []):
        name = topic["name"]
        is_fifo = topic.get("fifo", False)

        physical_name = f"{name}.fifo" if is_fifo else name
        env_var_name = topic.get("env_var", f"SNS_{name.upper().replace('-', '_')}_TOPIC_ARN")
        mappings[env_var_name] = f"{LOCALSTACK_SNS_ARN}{physical_name}"

    # Update existing or append to .env
    for key, value in mappings.items():
        pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
        if pattern.search(env_content):
            env_content = pattern.sub(f"{key}={value}", env_content)
            logger.info(f"Updated {key}")
        else:
            if not env_content.endswith("\n"):
                env_content += "\n"
            env_content += f"{key}={value}\n"
            logger.info(f"Added {key}")

    env_path.write_text(env_content, encoding="utf-8")
    logger.info("Successfully synchronized Topology URLs to root .env")


if __name__ == "__main__":
    main()
