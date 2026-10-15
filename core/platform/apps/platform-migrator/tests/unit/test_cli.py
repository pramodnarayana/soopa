"""
Unit Tests for Platform Migrator CLI
"""

import sys

import pytest
from platform_migrator.cli import handle_migrate, handle_seed, main


def test_handle_migrate_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "platform_migrator.cli.run_platform_domain_migrations",
        lambda: calls.append("platform"),
    )
    monkeypatch.setattr(
        "platform_migrator.cli.run_edi_domain_migrations",
        lambda: calls.append("edi"),
    )

    handle_migrate("platform")
    assert calls == ["platform"]


def test_handle_migrate_edi(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "platform_migrator.cli.run_platform_domain_migrations",
        lambda: calls.append("platform"),
    )
    monkeypatch.setattr(
        "platform_migrator.cli.run_edi_domain_migrations",
        lambda: calls.append("edi"),
    )

    handle_migrate("edi")
    assert calls == ["edi"]


def test_handle_migrate_all(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "platform_migrator.cli.run_platform_domain_migrations",
        lambda: calls.append("platform"),
    )
    monkeypatch.setattr(
        "platform_migrator.cli.run_edi_domain_migrations",
        lambda: calls.append("edi"),
    )

    handle_migrate("all")
    assert calls == ["platform", "edi"]


def test_handle_migrate_invalid_domain() -> None:
    with pytest.raises(ValueError, match="Unknown migration domain 'unknown'"):
        handle_migrate("unknown")


def test_handle_seed_dispatches_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "platform_migrator.cli.run_domain_seeds",
        lambda domain: calls.append(domain),
    )

    handle_seed("ucp")
    assert calls == ["ucp"]


def test_main_migrate_cli_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(sys, "argv", ["platform-migrator", "migrate", "--domain", "edi"])
    monkeypatch.setattr(
        "platform_migrator.cli.handle_migrate",
        lambda domain: calls.append(domain),
    )

    main()
    assert calls == ["edi"]


def test_main_seed_cli_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(sys, "argv", ["platform-migrator", "seed", "--domain", "ucp"])
    monkeypatch.setattr(
        "platform_migrator.cli.handle_seed",
        lambda domain: calls.append(domain),
    )

    main()
    assert calls == ["ucp"]
