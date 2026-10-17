#!/usr/bin/env python3
"""
Utility script to stop OpenAS2 and clean all runtime data for a clean slate.
"""

import shutil
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OPENAS2_COMPOSE = REPO_ROOT / "tools" / "openas2" / "docker-compose.yml"
OPENAS2_DATA_DIR = REPO_ROOT / "tools" / "openas2" / "data"

DOCKER_BIN = shutil.which("docker")

REQUIRED_DIRS = [
    OPENAS2_DATA_DIR / "outbox" / "FLOWWOLF_LOCAL_AS2",
    OPENAS2_DATA_DIR / "outbox" / "FLOWWOLF_STAGING_AS2",
    OPENAS2_DATA_DIR / "outbox" / "FLOWWOLF_AWS_AS2",
    OPENAS2_DATA_DIR / "outbox" / "error",
    OPENAS2_DATA_DIR / "inbox",
    OPENAS2_DATA_DIR / "resend",
    OPENAS2_DATA_DIR / "msgheaders",
]


def stop_openas2_container() -> None:
    logger.info("Stopping and removing OpenAS2 container...")
    if not DOCKER_BIN:
        logger.warning("docker binary not found in PATH, skipping container stop")
        return
    try:
        subprocess.run(  # noqa: S603 - Dynamic docker executable resolved safely via shutil.which
            [DOCKER_BIN, "compose", "-f", str(OPENAS2_COMPOSE), "down", "-v"],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Failed to stop OpenAS2 via docker compose", error=str(exc))


def clean_openas2_runtime_data() -> None:
    logger.info("Cleaning OpenAS2 runtime data directories...", path=str(OPENAS2_DATA_DIR))
    if OPENAS2_DATA_DIR.exists():
        for item in OPENAS2_DATA_DIR.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except OSError as exc:
                logger.warning("Failed to remove item", path=str(item), error=str(exc))

    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    logger.info("OpenAS2 runtime directories reset successfully.")


def main() -> None:
    stop_openas2_container()
    clean_openas2_runtime_data()


if __name__ == "__main__":
    main()
