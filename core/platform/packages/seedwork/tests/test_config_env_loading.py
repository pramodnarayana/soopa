"""Unit tests for pure, non-mutating configuration loading in seedwork."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import Field

from seedwork.domain.exceptions import ErrorCode
from seedwork.infra.config import (
    DEFAULT_ENV_FILE_NAME,
    ENV_FILE_SELECTOR_VAR,
    CleanBaseSettings,
    ConfigurationError,
    load_repo_env,
    load_settings,
    load_settings_safely,
    resolve_env_file_path,
)


class _SampleRequiredSettings(CleanBaseSettings):
    strict_required_var: str = Field(validation_alias="STRICT_REQUIRED_VAR")


class _SampleSharedSettings(CleanBaseSettings):
    shared_config_key: str = Field(validation_alias="SHARED_CONFIG_KEY", default="")
    only_in_dot_env: str = Field(validation_alias="ONLY_IN_DOT_ENV", default="")


def test_resolve_env_file_path_defaults_to_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_FILE_SELECTOR_VAR, raising=False)
    assert resolve_env_file_path(tmp_path) is None  # .env doesn't exist yet
    (tmp_path / DEFAULT_ENV_FILE_NAME).write_text("A=1\n")
    assert resolve_env_file_path(tmp_path) == tmp_path / DEFAULT_ENV_FILE_NAME


def test_resolve_env_file_path_honors_relative_and_absolute_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, ".env.example")
    assert resolve_env_file_path(tmp_path) == tmp_path / ".env.example"

    custom_abs = tmp_path / "configs" / "ci.env"
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(custom_abs))
    assert resolve_env_file_path(tmp_path) == custom_abs


def test_clean_base_settings_loads_from_selected_env_file_without_mutating_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env = tmp_path / ".env"
    dot_env.write_text(
        "ONLY_IN_DOT_ENV=leaked_value\nSHARED_CONFIG_KEY=from_dot_env\n",
        encoding="utf-8",
    )
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text(
        "SHARED_CONFIG_KEY=from_example\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("ONLY_IN_DOT_ENV", raising=False)
    monkeypatch.delenv("SHARED_CONFIG_KEY", raising=False)
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env_example))

    settings = _SampleSharedSettings()

    assert settings.shared_config_key == "from_example"
    assert settings.only_in_dot_env == ""
    # Purity guarantee: os.environ is NOT mutated!
    assert "SHARED_CONFIG_KEY" not in os.environ
    assert "ONLY_IN_DOT_ENV" not in os.environ


def test_clean_base_settings_process_environment_overrides_file_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text("SHARED_CONFIG_KEY=from_file\n", encoding="utf-8")

    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env_example))
    monkeypatch.setenv("SHARED_CONFIG_KEY", "from_parent_process")

    settings = _SampleSharedSettings()
    assert settings.shared_config_key == "from_parent_process"


def test_load_repo_env_parses_file_without_mutating_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text("PARSED_KEY=parsed_val\n", encoding="utf-8")

    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env_example))
    monkeypatch.delenv("PARSED_KEY", raising=False)

    parsed = load_repo_env(repo_root=tmp_path)
    assert parsed["PARSED_KEY"] == "parsed_val"
    assert "PARSED_KEY" not in os.environ


def test_load_settings_safely_fails_when_var_exists_only_in_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env = tmp_path / ".env"
    dot_env.write_text("STRICT_REQUIRED_VAR=present_in_local_dot_env\n", encoding="utf-8")
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text("UNRELATED_KEY=1\n", encoding="utf-8")

    monkeypatch.delenv("STRICT_REQUIRED_VAR", raising=False)
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env_example))

    with pytest.raises(SystemExit) as exc_info:
        load_settings_safely(_SampleRequiredSettings)

    assert exc_info.value.code == 1


def test_load_settings_returns_result_err_on_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text("UNRELATED_KEY=1\n", encoding="utf-8")

    monkeypatch.delenv("STRICT_REQUIRED_VAR", raising=False)
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env_example))

    result = load_settings(_SampleRequiredSettings)
    assert result.is_err
    assert not result.is_ok
    err = result.unwrap_err()
    assert isinstance(err, ConfigurationError)
    assert err.code == ErrorCode.VALIDATION_FAILED
    assert any("STRICT_REQUIRED_VAR" in field for field in err.missing_fields)


def test_load_settings_returns_result_ok_when_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env = tmp_path / ".env"
    dot_env.write_text("STRICT_REQUIRED_VAR=configured_value\n", encoding="utf-8")

    monkeypatch.delenv("STRICT_REQUIRED_VAR", raising=False)
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(dot_env))

    result = load_settings(_SampleRequiredSettings)
    assert result.is_ok
    assert not result.is_err
    settings = result.unwrap()
    assert settings.strict_required_var == "configured_value"
