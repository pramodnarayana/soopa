"""Architectural and IoC unit tests enforcing domain purity of generic IP engine, UI, and test suites."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector
from ip.engine.bootstrap.api_provider import IpApiProvider
from ip.engine.bootstrap.container import Container, create_engine_catalog_registry

_VERTICAL_VOCAB_PATTERN = re.compile(
    r"(?:\b(?:"
    r"itron|mercurygate|mercury_gate|meter|meters|meter_id|"
    r"meter_reads?|meter_readings?|meter_serial|"
    r"service_points?|service_point_id|kwh|"
    r"smart\s+grid|grid-utility|gridpower|sap[-_]isu|"
    r"MDM_READING|MDM_SERVICE_POINT|TMS_LOAD|TMS_CARRIER"
    r")\b|"
    r"\b(?:itron|ami|mdm|tms|energy)_[a-z0-9_]+\b|"
    r"\b(?:itron|ami|mdm|tms|energy)\.[a-z0-9_.]+\b)",
    re.IGNORECASE,
)

_ALLOWED_SOLUTION_TEST_PREFIXES: tuple[str, ...] = (
    "unit/solutions/",
    "unit/application/domains/",
    "unit/application/transformers/",
    "integration/domains/",
    "integration/database/test_tenant_domain_migrations.py",
    "e2e/test_energy_pipeline_e2e.py",
    "e2e/test_tms_pipeline_e2e.py",
    "unit/engine/test_engine_domain_purity.py",
)


def _ip_pkg_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[7]


def _is_generic_engine_test(py_file: Path, tests_root: Path) -> bool:
    rel = py_file.relative_to(tests_root).as_posix()
    return not any(rel.startswith(prefix) for prefix in _ALLOWED_SOLUTION_TEST_PREFIXES)


def test_ip_engine_files_do_not_import_ip_solutions() -> None:
    engine_dir = _ip_pkg_root() / "src" / "ip" / "engine"
    offenders: list[str] = []
    for py_file in sorted(engine_dir.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        if "ip.solutions" in text:
            offenders.append(str(py_file.relative_to(_ip_pkg_root())))

    assert offenders == []


def test_ip_engine_files_exclude_vertical_domain_vocabulary() -> None:
    engine_dir = _ip_pkg_root() / "src" / "ip" / "engine"
    offenders: list[str] = []
    for py_file in sorted(engine_dir.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        match = _VERTICAL_VOCAB_PATTERN.search(text)
        if match is not None:
            offenders.append(f"{py_file.relative_to(_ip_pkg_root())}: {match.group(0)}")

    assert offenders == []


def test_generic_ip_tests_do_not_reference_ip_solutions() -> None:
    tests_dir = _ip_pkg_root() / "tests"
    offenders: list[str] = []
    for py_file in sorted(tests_dir.rglob("*.py")):
        if not _is_generic_engine_test(py_file, tests_dir):
            continue
        text = py_file.read_text(encoding="utf-8")
        if "ip.solutions" in text:
            offenders.append(str(py_file.relative_to(tests_dir)))

    assert offenders == []


def test_generic_ip_tests_exclude_vertical_domain_vocabulary() -> None:
    tests_dir = _ip_pkg_root() / "tests"
    offenders: list[str] = []
    for py_file in sorted(tests_dir.rglob("*.py")):
        if not _is_generic_engine_test(py_file, tests_dir):
            continue
        text = py_file.read_text(encoding="utf-8")
        match = _VERTICAL_VOCAB_PATTERN.search(text)
        if match is not None:
            offenders.append(f"{py_file.relative_to(tests_dir)}: {match.group(0)}")

    assert offenders == []


def test_ip_ui_package_excludes_vertical_domain_vocabulary() -> None:
    ui_src_dir = _repo_root() / "apps" / "ip" / "packages" / "ui" / "src"
    offenders: list[str] = []
    for ui_file in sorted(ui_src_dir.rglob("*")):
        if ui_file.suffix not in {".ts", ".tsx"}:
            continue
        if ui_file.name == "domain-purity.test.ts":
            continue
        text = ui_file.read_text(encoding="utf-8")
        match = _VERTICAL_VOCAB_PATTERN.search(text)
        if match is not None:
            offenders.append(f"{ui_file.relative_to(ui_src_dir)}: {match.group(0)}")

    assert offenders == []


def test_tach_config_forbids_ip_engine_dependencies_on_ip_solutions() -> None:
    tach_path = _repo_root() / "tach.toml"
    tach_data = tomllib.loads(tach_path.read_text(encoding="utf-8"))
    modules = tach_data.get("modules", [])

    engine_solution_deps: list[str] = []
    for mod in modules:
        path = str(mod.get("path", ""))
        if path.startswith("ip.engine"):
            for dep in mod.get("depends_on", []):
                if str(dep).startswith("ip.solutions"):
                    engine_solution_deps.append(f"{path} -> {dep}")

    assert engine_solution_deps == []


def test_engine_container_defaults_remain_domain_agnostic() -> None:
    container = Container()
    container.config.allow_private_ips.from_value(False)

    catalog = container.catalog_registry()
    app_ids = {summary.app_id for summary in catalog.list_apps()}
    assert app_ids == {"http", "sftp"}

    transformer_reg = container.transformer_registry()
    assert transformer_reg.list_transformers() == ()

    stitch_cat = container.stitch_catalog()
    assert stitch_cat.list_stitches(tenant_id="ten_1") == ()

    provider = IpApiProvider()
    assert {s.app_id for s in provider.get_catalog_registry().list_apps()} == {"http", "sftp"}
    assert provider.create_transformer_registry().list_transformers() == ()


def test_lifespan_delegates_to_composition_root_without_iac_mutation_or_raw_env() -> None:
    lifespan_file = _ip_pkg_root() / "src" / "ip" / "engine" / "bootstrap" / "lifespan.py"
    source = lifespan_file.read_text(encoding="utf-8")

    assert "aioboto3" not in source
    assert "create_bucket" not in source
    assert "os.getenv" not in source
    assert "SqlAlchemyIpTenantResolver" not in source
    assert "create_ip_tenant_resolver" in source


def test_engine_worker_modules_disallow_standalone_main_entrypoints() -> None:
    workers_dir = _ip_pkg_root() / "src" / "ip" / "engine" / "bootstrap" / "workers"
    offenders: list[str] = []
    for worker_file in sorted(workers_dir.glob("ip_*_worker.py")):
        source = worker_file.read_text(encoding="utf-8")
        if "async def main(" in source or '__name__ == "__main__"' in source:
            offenders.append(worker_file.name)

    assert offenders == []


def test_engine_catalog_registry_forwards_allow_private_ips_to_sftp() -> None:
    strict_registry = create_engine_catalog_registry(allow_private_ips=False)
    strict_sftp = strict_registry.get_connector("sftp").unwrap()
    assert isinstance(strict_sftp, SftpConnector)
    assert strict_sftp._allow_local is False

    local_registry = create_engine_catalog_registry(allow_private_ips=True)
    local_sftp = local_registry.get_connector("sftp").unwrap()
    assert isinstance(local_sftp, SftpConnector)
    assert local_sftp._allow_local is True
