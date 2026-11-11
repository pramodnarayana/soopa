"""Unit tests for PEP 610 dynamic workspace hot-reload directory discovery."""

from __future__ import annotations

import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from run_dev_server import (
    collect_installed_editable_reload_dirs,
    discover_editable_reload_dirs,
    parse_editable_package_src_dir,
)


@dataclass(frozen=True)
class _FakeDistribution:
    direct_url_text: str | None

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self.direct_url_text
        return None


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


def test_parse_editable_package_src_dir_applies_pep610_subdirectory(tmp_path: Path) -> None:
    monorepo_root = tmp_path / "workspace"
    subpkg_src = monorepo_root / "apps" / "ip" / "packages" / "ip" / "src"
    subpkg_src.mkdir(parents=True)

    payload_with_subdir = json.dumps(
        {
            "url": monorepo_root.as_uri(),
            "subdirectory": "apps/ip/packages/ip",
            "dir_info": {"editable": True},
        }
    )
    payload_non_string_subdir = json.dumps(
        {
            "url": monorepo_root.as_uri(),
            "subdirectory": 123,
            "dir_info": {"editable": True},
        }
    )
    payload_traversal_subdir = json.dumps(
        {
            "url": monorepo_root.as_uri(),
            "subdirectory": "../escape",
            "dir_info": {"editable": True},
        }
    )

    assert parse_editable_package_src_dir(payload_with_subdir) == subpkg_src.resolve()
    assert parse_editable_package_src_dir(payload_non_string_subdir) == monorepo_root.resolve()
    assert parse_editable_package_src_dir(payload_traversal_subdir) is None


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


def test_collect_installed_editable_reload_dirs_finds_workspace_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_cwd = tmp_path / "cwd_without_src"
    isolated_cwd.mkdir(parents=True)
    monkeypatch.chdir(isolated_cwd)

    editable_alpha_src = tmp_path / "packages" / "alpha" / "src"
    editable_beta_src = tmp_path / "repo" / "apps" / "beta" / "src"
    non_editable_gamma_src = tmp_path / "packages" / "gamma" / "src"
    editable_alpha_src.mkdir(parents=True)
    editable_beta_src.mkdir(parents=True)
    non_editable_gamma_src.mkdir(parents=True)

    fake_distributions = [
        _FakeDistribution(
            json.dumps(
                {
                    "url": (tmp_path / "repo").as_uri(),
                    "subdirectory": "apps/beta",
                    "dir_info": {"editable": True},
                }
            )
        ),
        _FakeDistribution(
            json.dumps(
                {
                    "url": editable_alpha_src.parent.as_uri(),
                    "dir_info": {"editable": True},
                }
            )
        ),
        _FakeDistribution(
            json.dumps(
                {
                    "url": non_editable_gamma_src.parent.as_uri(),
                    "dir_info": {"editable": False},
                }
            )
        ),
        _FakeDistribution(None),
    ]
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: fake_distributions)

    dirs = collect_installed_editable_reload_dirs()
    assert dirs == sorted(
        [
            str(editable_alpha_src.resolve()),
            str(editable_beta_src.resolve()),
        ]
    )
