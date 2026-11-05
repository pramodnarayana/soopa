import os
import sys
from pathlib import Path
from typing import TypeVar

import structlog
from dotenv import dotenv_values
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from seedwork.infra.repo_root import find_repo_root

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseSettings)

ENV_FILE_SELECTOR_VAR = "SOOPA_ENV_FILE"
DEFAULT_ENV_FILE_NAME = ".env"


def resolve_env_file_path(repo_root: Path) -> Path:
    """Resolve the active environment file path for a repository root.

    Honors ``SOOPA_ENV_FILE`` when set in process memory so verification runs
    can load ``.env.example`` without mutating ``.env`` on disk.
    """
    selector = os.environ.get(ENV_FILE_SELECTOR_VAR, "").strip() or DEFAULT_ENV_FILE_NAME
    candidate = Path(selector)
    if candidate.is_absolute():
        return candidate
    return repo_root / candidate


def load_repo_env(*, repo_root: Path | None = None, override: bool = False) -> dict[str, str]:
    """Load key-value pairs from the active environment file into ``os.environ``.

    When ``SOOPA_ENV_FILE`` is set, strictly loads only that file and never
    falls back to ``.env`` on disk. In container images without a ``.git``
    directory, silently skips file loading unless an absolute ``SOOPA_ENV_FILE``
    path is provided.
    """
    selector = os.environ.get(ENV_FILE_SELECTOR_VAR, "").strip()
    if repo_root is not None:
        env_path = resolve_env_file_path(repo_root)
    elif selector and Path(selector).is_absolute():
        env_path = Path(selector)
    else:
        try:
            detected_root = find_repo_root(Path(__file__).resolve())
        except RuntimeError:
            return {}
        env_path = resolve_env_file_path(detected_root)

    if not env_path.is_file():
        return {}

    parsed = dotenv_values(env_path)
    loaded: dict[str, str] = {}
    for key, val in parsed.items():
        if val is None:
            continue
        loaded[key] = val
        if override or key not in os.environ:
            os.environ[key] = val

    return loaded


def _inject_env_file_to_environ() -> None:
    """Inject the resolved environment file into ``os.environ`` without overriding."""
    load_repo_env(override=False)


def load_settings_safely(settings_class: type[T]) -> T:
    """Safely instantiate a Pydantic ``BaseSettings`` class.

    If required environment variables are missing, intercepts ``ValidationError``
    and logs a structured diagnostic error before exiting the process.
    """
    _inject_env_file_to_environ()

    try:
        return settings_class()
    except ValidationError as val_err:
        missing_fields: list[str] = []
        for err in val_err.errors():
            loc = ".".join(str(loc_item) for loc_item in err.get("loc", ()))
            msg = err.get("msg", "")
            missing_fields.append(f"{loc} ({msg})")

        logger.exception(
            "worker_startup_configuration_error",
            reason="One or more required environment variables are missing.",
            missing_fields=missing_fields,
            remedy="Check .env.example and ensure all required variables are set.",
        )
        sys.exit(1)
    except Exception:
        logger.exception("worker_startup_failed", reason="Startup initialization error")
        sys.exit(1)
