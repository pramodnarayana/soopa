"""Unit tests for PEP 610 dynamic workspace hot-reload directory discovery."""

from __future__ import annotations

import json
from pathlib import Path

from run_dev_server import (
    collect_installed_editable_reload_dirs,
    discover_editable_reload_dirs,
    parse_editable_package_src_dir,
)


def test_parse_editable_package_src_dir_prefers_src_subdirectory(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "sample_pkg"
    src_dir = pkg_dir / "src"
    src_dir.mkdir(parents=True)

    payload = json.dumps(
        {
            "url": pkg_dir.as_uri(),
            "dir_info": {"editable": True},
        }
    )

    resolved = parse_editable_package_src_dir(payload)
    assert resolved == src_dir.resolve()


def test_parse_editable_package_src_dir_ignores_non_editable_or_non_file_urls(
    tmp_path: Path,
) -> None:
    pkg_dir = tmp_path / "wheel_pkg"
    pkg_dir.mkdir(parents=True)

    non_editable = json.dumps({"url": pkg_dir.as_uri(), "dir_info": {"editable": False}})
    vcs_url = json.dumps({"url": "https://example.com/pkg.whl", "dir_info": {"editable": True}})

    assert parse_editable_package_src_dir(non_editable) is None
    assert parse_editable_package_src_dir(vcs_url) is None
    assert parse_editable_package_src_dir("{invalid_json") is None


def test_discover_editable_reload_dirs_deduplicates_and_sorts(tmp_path: Path) -> None:
    pkg_b = tmp_path / "b_pkg" / "src"
    pkg_a = tmp_path / "a_pkg" / "src"
    pkg_b.mkdir(parents=True)
    pkg_a.mkdir(parents=True)

    payload_b = json.dumps({"url": pkg_b.parent.as_uri(), "dir_info": {"editable": True}})
    payload_a = json.dumps({"url": pkg_a.parent.as_uri(), "dir_info": {"editable": True}})

    result = discover_editable_reload_dirs([payload_b, payload_a, payload_b])
    assert result == [str(pkg_a.resolve()), str(pkg_b.resolve())]


def test_collect_installed_editable_reload_dirs_finds_workspace_packages() -> None:
    dirs = collect_installed_editable_reload_dirs()
    assert len(dirs) > 0
    assert all(Path(d).is_dir() for d in dirs)
