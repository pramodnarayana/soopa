"""Unit tests for SOOPA_ENV_FILE clean-room configuration loading in seedwork."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import Field
from pydantic_settings import BaseSettings

from seedwork.infra.config import (
    DEFAULT_ENV_FILE_NAME,
    ENV_FILE_SELECTOR_VAR,
    load_repo_env,
    load_settings_safely,
    resolve_env_file_path,
)


class _SampleRequiredSettings(BaseSettings):
    strict_required_var: str = Field(validation_alias="STRICT_REQUIRED_VAR")


def test_resolve_env_file_path_defaults_to_dot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_FILE_SELECTOR_VAR, raising=False)
    assert resolve_env_file_path(tmp_path) == tmp_path / DEFAULT_ENV_FILE_NAME


def test_resolve_env_file_path_honors_relative_and_absolute_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, ".env.example")
    assert resolve_env_file_path(tmp_path) == tmp_path / ".env.example"

    custom_abs = tmp_path / "configs" / "ci.env"
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(custom_abs))
    assert resolve_env_file_path(tmp_path) == custom_abs


def test_load_repo_env_isolates_selected_file_from_dot_env_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env = tmp_path / ".env"
    dot_env.write_text(
        "ONLY_IN_DOT_ENV=leaked_value\nSHARED_CONFIG_KEY=from_dot_env\n",
        encoding="utf-8",
    )
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text(
        "SHARED_CONFIG_KEY=from_example # inline comment\n"
        'STRUCTURED_JSON_KEY={"keyId": "123", "mode": "clean"}\n',
        encoding="utf-8",
    )

    monkeypatch.delenv("ONLY_IN_DOT_ENV", raising=False)
    monkeypatch.delenv("SHARED_CONFIG_KEY", raising=False)
    monkeypatch.delenv("STRUCTURED_JSON_KEY", raising=False)
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, ".env.example")

    loaded = load_repo_env(repo_root=tmp_path)

    assert loaded["SHARED_CONFIG_KEY"] == "from_example"
    assert os.environ["SHARED_CONFIG_KEY"] == "from_example"
    assert os.environ["STRUCTURED_JSON_KEY"] == '{"keyId": "123", "mode": "clean"}'
    assert "ONLY_IN_DOT_ENV" not in os.environ


def test_load_repo_env_preserves_existing_process_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dot_env_example = tmp_path / ".env.example"
    dot_env_example.write_text("OVERRIDE_TARGET_KEY=from_file\n", encoding="utf-8")

    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, ".env.example")
    monkeypatch.setenv("OVERRIDE_TARGET_KEY", "from_parent_process")

    load_repo_env(repo_root=tmp_path, override=False)
    assert os.environ["OVERRIDE_TARGET_KEY"] == "from_parent_process"


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
