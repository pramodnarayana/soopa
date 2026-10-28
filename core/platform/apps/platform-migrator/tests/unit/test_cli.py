"""
Unit Tests for Platform Migrator CLI (Pure DI, Zero Monkeypatching)
"""

import pytest
from platform_migrator.cli import handle_migrate, handle_seed, main
from platform_migrator.runners.seed_runner import run_domain_seeds


def test_handle_migrate_platform() -> None:
    calls: list[str] = []
    handle_migrate("platform", migration_runner=lambda: calls.append("platform"))
    assert calls == ["platform"]


def test_handle_migrate_rejects_all_domain() -> None:
    with pytest.raises(ValueError, match="Unknown migration domain 'all'"):
        handle_migrate("all", migration_runner=lambda: None)


def test_handle_migrate_invalid_domain() -> None:
    with pytest.raises(ValueError, match="Unknown migration domain 'unknown'"):
        handle_migrate("unknown", migration_runner=lambda: None)


def test_handle_seed_dispatches_domain() -> None:
    calls: list[str] = []
    handle_seed("ucp", seed_runner=lambda domain: calls.append(domain))
    assert calls == ["ucp"]


def test_main_migrate_cli_arguments() -> None:
    calls: list[str] = []
    exit_code = main(
        args=["migrate", "--domain", "platform"],
        migration_runner=lambda: calls.append("platform"),
    )
    assert exit_code == 0
    assert calls == ["platform"]


def test_main_seed_cli_arguments() -> None:
    calls: list[str] = []
    exit_code = main(
        args=["seed", "--domain", "ucp"],
        seed_runner=lambda domain: calls.append(domain),
    )
    assert exit_code == 0
    assert calls == ["ucp"]


def test_main_seed_default_platform() -> None:
    calls: list[str] = []
    exit_code = main(
        args=["seed"],
        seed_runner=lambda domain: calls.append(domain),
    )
    assert exit_code == 0
    assert calls == ["platform"]


def test_main_runner_exception_returns_exit_code_one() -> None:
    def failing_runner() -> None:
        raise RuntimeError("database unreachable")

    exit_code = main(
        args=["migrate", "--domain", "platform"],
        migration_runner=failing_runner,
    )
    assert exit_code == 1


def test_main_seed_ip_domain_and_isolated_seed_runner() -> None:
    calls: list[str] = []
    exit_code = main(
        args=["seed", "--domain", "ip"],
        seed_runner=lambda domain: calls.append(domain),
    )
    assert exit_code == 0
    assert calls == ["ip"]

    ip_scripts: list[str] = []
    run_domain_seeds("ip", script_executor=ip_scripts.append)
    assert ip_scripts == [
        "apps/ip/scripts/seed.py",
        "apps/ip/scripts/seed_jobs.py",
    ]

    edi_scripts: list[str] = []
    run_domain_seeds("edi", script_executor=edi_scripts.append)
    assert edi_scripts == [
        "apps/edi/scripts/seed_jobs.py",
        "apps/edi/apps/edi-as2-server/scripts/seed.py",
    ]
