import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import structlog
from dotenv import dotenv_values
from pydantic import ValidationError
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from seedwork.domain.exceptions import DomainError, ErrorCode, Result
from seedwork.domain.types import JsonDict
from seedwork.infra.repo_root import find_repo_root

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseSettings)

ENV_FILE_SELECTOR_VAR = "SOOPA_ENV_FILE"
DEFAULT_ENV_FILE_NAME = ".env"


@dataclass(frozen=True)
class ConfigurationError:
    """Structured diagnostic failure when environment configuration fails validation."""

    message: str
    code: ErrorCode = ErrorCode.VALIDATION_FAILED
    missing_fields: tuple[str, ...] = ()
    remedy: str = ""


class PlatformConfigurationError(DomainError):
    """Raised when configuration resolution fails at an operational boundary."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | str = ErrorCode.VALIDATION_FAILED,
        details: JsonDict | None = None,
        missing_fields: tuple[str, ...] = (),
        remedy: str = "",
    ) -> None:
        super().__init__(message, code=code, details=details)
        self.missing_fields = missing_fields
        self.remedy = remedy


def resolve_env_file_path(repo_root: Path | None = None) -> Path | None:
    """Resolve the active environment file path without mutating process memory.

    Honors ``SOOPA_ENV_FILE`` when set in process memory so verification runs
    can load ``.env.example`` without mutating ``.env`` on disk.
    """
    selector = os.environ.get(ENV_FILE_SELECTOR_VAR, "").strip()
    if selector:
        candidate = Path(selector)
        if candidate.is_absolute():
            return candidate
        if repo_root is not None:
            return repo_root / candidate
        try:
            detected_root = find_repo_root(Path(__file__).resolve())
            return detected_root / candidate
        except RuntimeError:
            return candidate

    target_root = repo_root
    if target_root is None:
        try:
            target_root = find_repo_root(Path(__file__).resolve())
        except RuntimeError:
            return None

    candidate = target_root / DEFAULT_ENV_FILE_NAME
    return candidate if candidate.is_file() else None


def resolve_anchored_path(raw_path: str, *, setting_name: str) -> str:
    """Resolve a configured filesystem path deterministically across monorepo services.

    - Absolute paths are normalized via ``os.path.normpath``.
    - Relative paths (e.g. ``.local/secrets``) are anchored to the monorepo root
      via ``find_repo_root()`` so services launched from different subdirectories
      always read and write the exact same directory.
    - Outside a git monorepo (e.g. production containers), relative paths fail fast.
    """
    cleaned = raw_path.strip()
    if not cleaned:
        raise ValueError(f"{setting_name} must not be empty.")

    candidate = Path(cleaned)
    if candidate.is_absolute():
        return os.path.normpath(cleaned)

    try:
        repo_root = find_repo_root(Path(__file__).resolve())
    except RuntimeError as exc:
        raise ValueError(
            f"{setting_name}='{cleaned}' must be an absolute path when running outside a "
            "monorepo workspace."
        ) from exc

    return str((repo_root / candidate).resolve())


def load_repo_env(*, repo_root: Path | None = None) -> dict[str, str]:
    """Parse key-value pairs from the active environment file into a dictionary.

    Pure, non-mutating parser: never modifies ``os.environ``.
    """
    env_path = resolve_env_file_path(repo_root)
    if env_path is None or not env_path.is_file():
        return {}

    parsed = dotenv_values(env_path)
    return {k: v for k, v in parsed.items() if v is not None}


class CleanBaseSettings(BaseSettings):
    """Enterprise BaseSettings with pure, non-mutating environment file resolution.

    Reads from the active environment file (honoring ``SOOPA_ENV_FILE``) directly into
    Pydantic internal state without writing a single key into ``os.environ``.
    Maintains strict 12-factor precedence:
    1. Explicit constructor arguments
    2. Real process environment variables
    3. Resolved environment file values
    4. Model defaults
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        env_file = resolve_env_file_path()
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(
                settings_cls,
                env_file=env_file if env_file and env_file.is_file() else None,
                env_file_encoding="utf-8",
            ),
            file_secret_settings,
        )


def load_settings(settings_class: type[T]) -> Result[T, ConfigurationError]:
    """Pure, non-terminating settings loader returning a first-class Result."""
    try:
        return Result.ok(settings_class())
    except ValidationError as val_err:
        missing_fields: list[str] = []
        for err in val_err.errors():
            loc = ".".join(str(loc_item) for loc_item in err.get("loc", ()))
            msg = err.get("msg", "")
            missing_fields.append(f"{loc} ({msg})")

        return Result.err(
            ConfigurationError(
                message=f"Configuration validation failed for {settings_class.__name__}",
                code=ErrorCode.VALIDATION_FAILED,
                missing_fields=tuple(missing_fields),
                remedy="Check .env.example and ensure all required variables are set.",
            )
        )
    except (ValueError, TypeError) as exc:
        return Result.err(
            ConfigurationError(
                message=f"Invalid configuration value for {settings_class.__name__}: {exc}",
                code=ErrorCode.VALIDATION_FAILED,
                missing_fields=(),
                remedy="Verify environment variable types and formats.",
            )
        )


def load_settings_safely(settings_class: type[T]) -> T:
    """Safely instantiate a Pydantic ``BaseSettings`` class without mutating ``os.environ``.

    Treats errors as first-class citizens via ``load_settings()``. If validation fails,
    logs a structured diagnostic error before terminating via ``SystemExit(1)`` to abort cleanly
    at operational boundary.
    """
    result = load_settings(settings_class)
    if result.is_err:
        err = result.unwrap_err()
        logger.error(
            "worker_startup_configuration_error",
            code=err.code.value,
            reason=err.message,
            missing_fields=list(err.missing_fields),
            remedy=err.remedy,
        )
        raise SystemExit(1)
    return result.unwrap()
