"""Centralized Pytest plugin enforcing isolated *_test PostgreSQL databases and SOOPA_ENV_FILE."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import IO

import dotenv
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Dialect, Engine

from database.utils import DEFAULT_TEST_DB_SUFFIX

ENV_FILE_SELECTOR_VAR = "SOOPA_ENV_FILE"
_GUARD_INSTALLED = False
_ORIGINAL_LOAD_DOTENV = dotenv.load_dotenv


def _guarded_postgresql_do_connect(
    dialect: Dialect,
    _conn_rec: object,
    _cargs: tuple[object, ...],
    cparams: MutableMapping[str, object],
) -> None:
    """Abort before opening a socket if any test attempts to connect to a non-test Postgres DB."""
    if dialect.name != "postgresql":
        return

    raw_db = cparams.get("database") or cparams.get("dbname") or ""
    db_name = str(raw_db).strip("/")
    if not db_name or (db_name != "test" and not db_name.endswith(DEFAULT_TEST_DB_SUFFIX)):
        raise RuntimeError(
            f"Refusing to run tests against non-test PostgreSQL database '{db_name or '<empty>'}'. "
            f"Expected a '*{DEFAULT_TEST_DB_SUFFIX}' database "
            "(run via 'pnpm test:integration' or 'infra/local/scripts/run_in_test_env.py')."
        )


def _env_isolated_load_dotenv(
    dotenv_path: str | os.PathLike[str] | None = None,
    stream: IO[str] | None = None,
    verbose: bool = False,
    override: bool = False,
    interpolate: bool = True,
    encoding: str | None = "utf-8",
) -> bool:
    """Redirect bare ``load_dotenv()`` calls in test files to ``SOOPA_ENV_FILE`` when set."""
    selected = os.environ.get(ENV_FILE_SELECTOR_VAR, "").strip()
    if selected and dotenv_path is None and stream is None:
        resolved_target: str | os.PathLike[str] | None = Path(selected)
        return _ORIGINAL_LOAD_DOTENV(
            dotenv_path=resolved_target,
            verbose=verbose,
            override=False,
            interpolate=interpolate,
            encoding=encoding,
        )
    return _ORIGINAL_LOAD_DOTENV(
        dotenv_path=dotenv_path,
        stream=stream,
        verbose=verbose,
        override=override,
        interpolate=interpolate,
        encoding=encoding,
    )


def install_pytest_database_guard() -> None:
    """Idempotently attach the global SQLAlchemy PostgreSQL connection guard."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    event.listen(Engine, "do_connect", _guarded_postgresql_do_connect)
    _GUARD_INSTALLED = True


def pytest_load_initial_conftests(
    early_config: pytest.Config,
    parser: pytest.Parser,
    args: list[str],
) -> None:
    """Activate PostgreSQL test-DB isolation before any package conftest.py imports."""
    _ = (early_config, parser, args)
    install_pytest_database_guard()
    dotenv.load_dotenv = _env_isolated_load_dotenv
