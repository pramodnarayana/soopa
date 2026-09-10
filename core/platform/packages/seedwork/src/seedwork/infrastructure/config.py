import os
import sys
from pathlib import Path
from typing import TypeVar

import structlog
from pydantic_settings import BaseSettings

from seedwork.infrastructure.repo_root import find_repo_root

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseSettings)


def _inject_env_file_to_environ() -> None:
    """
    Locates the repository root .env file and injects it into os.environ.
    This guarantees that underlying C libraries (like aioboto3) have access
    to the exact same environment variables as Pydantic, providing true parity
    between local development and production Docker containers.

    In production Docker images there is no .git directory; the function
    silently skips injection and relies entirely on os.environ in that case.
    """
    try:
        repo_root = find_repo_root(Path(__file__).resolve())
    except RuntimeError:
        # No .git directory found — we are running inside a Docker container.
        # Settings will be loaded from os.environ injected by the orchestrator.
        return

    env_path = repo_root / ".env"

    if not env_path.is_file():
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # Strip quotes if present
                if len(val) >= 2 and val.startswith(('"', "'")) and val.endswith(('"', "'")):
                    val = val[1:-1]

                # Only inject if not already present (respect environment overrides)
                if key not in os.environ:
                    os.environ[key] = val


def load_settings_safely(settings_class: type[T]) -> T:
    """
    Safely instantiates a Pydantic BaseSettings class.
    If required environment variables are missing, it intercepts the ValidationError
    and logs a human-readable structured error before exiting the process.
    """
    _inject_env_file_to_environ()

    try:
        # Pydantic will now pull natively from os.environ
        return settings_class()
    except Exception as e:
        if e.__class__.__name__ == "ValidationError":
            missing_fields = []
            for err in getattr(e, "errors", list)():
                loc = ".".join(str(loc_item) for loc_item in err.get("loc", []))
                msg = err.get("msg", "")
                missing_fields.append(f"{loc} ({msg})")

            logger.exception(
                "worker_startup_configuration_error",
                reason="One or more required environment variables are missing from your .env file.",
                missing_fields=missing_fields,
                remedy="Please check .env.example and ensure all required variables are set.",
            )
        else:
            logger.exception("worker_startup_failed", reason="Startup initialization error")
        sys.exit(1)
