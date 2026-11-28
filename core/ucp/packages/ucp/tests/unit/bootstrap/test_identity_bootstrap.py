"""Unit tests for IdP-agnostic platform bootstrap config and host-consistent reset scripts."""

from __future__ import annotations

import json
from pathlib import Path

from seedwork.infra.repo_root import find_repo_root

from ucp.bootstrap.identity_bootstrap import PLATFORM_ADMIN_ROLE_NAME, PlatformSeedConfig


def test_platform_seed_config_is_frozen_and_provider_agnostic() -> None:
    cfg = PlatformSeedConfig(
        platform_org_id="soopa-platform",
        platform_admin_id="soopa-platform/platform_admin",
        platform_admin_email="admin@flowwolf.io",
        idp_issuer="https://identity.staging.flowwolf.io",
    )
    assert PLATFORM_ADMIN_ROLE_NAME == "PlatformAdmin"
    assert cfg.platform_org_id == "soopa-platform"
    assert cfg.idp_issuer == "https://identity.staging.flowwolf.io"


def test_package_json_reset_and_infra_up_use_host_seed_and_provider_agnostic_identity() -> None:
    repo_root = find_repo_root(Path(__file__).resolve())
    pkg = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    scripts: dict[str, str] = pkg["scripts"]

    assert "db-seed" not in scripts["infra:up"]
    assert "pnpm db:seed" in scripts["infra:up"]
    assert "clear_zitadel" not in scripts["infra:clean-identity-org"]
    assert "infra/local/identity/bootstrap.py" in scripts["infra:clean-identity-org"]

    for reset_script in ("infra-reset", "infra-reset:edi", "ucp-reset", "soft-reset"):
        cmd = scripts[reset_script]
        assert cmd.index("pnpm infra:start-identity") < cmd.index("pnpm infra:clean-identity-org")
