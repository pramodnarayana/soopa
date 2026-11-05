"""Unit tests for Zitadel reset drift verification and host-consistent reset scripts."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import httpx
import pytest
from identity.adapters.outbound.zitadel import ZitadelMachineAuthenticationError
from seedwork.infra.repo_root import find_repo_root

from ucp.bootstrap.identity_bootstrap import (
    ZitadelDriftReason,
    ZitadelIdentityConfig,
    cleanup_non_platform_zitadel_orgs,
    verify_zitadel_platform_alignment,
)


class _StubAccessTokenProvider:
    def __init__(self, issued_bearer: str | None = None, error: str | None = None) -> None:
        self._issued_bearer = issued_bearer or secrets.token_urlsafe(16)
        self._error = error

    @property
    def issued_bearer(self) -> str:
        return self._issued_bearer

    async def get_access_token(self) -> str:
        if self._error is not None:
            raise ZitadelMachineAuthenticationError(self._error)
        return self._issued_bearer


@pytest.mark.asyncio
async def test_verify_zitadel_platform_alignment_rejects_missing_env_credentials() -> None:
    cfg = ZitadelIdentityConfig(
        zitadel_url="http://ucp.localhost:8080",
        machine_key="",
        platform_org_id="397365687661625347",
        platform_admin_id="397365688483708931",
        ucp_project_id="397365690295648259",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200))
    ) as client:
        result = await verify_zitadel_platform_alignment(
            config=cfg,
            token_provider=_StubAccessTokenProvider(),
            http_client=client,
            ready_timeout_seconds=0.5,
        )
    assert result.aligned is False
    assert result.reason == ZitadelDriftReason.MISSING_CREDENTIALS


@pytest.mark.asyncio
async def test_verify_zitadel_platform_alignment_detects_machine_key_drift() -> None:
    cfg = ZitadelIdentityConfig(
        zitadel_url="http://ucp.localhost:8080",
        machine_key='{"keyId":"1","key":"pem","userId":"2"}',
        platform_org_id="397365687661625347",
        platform_admin_id="397365688483708931",
        ucp_project_id="397365690295648259",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/debug/ready":
            return httpx.Response(200, text="ok")
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_zitadel_platform_alignment(
            config=cfg,
            token_provider=_StubAccessTokenProvider(error="invalid_grant: key not found"),
            http_client=client,
            ready_timeout_seconds=0.5,
        )
    assert result.aligned is False
    assert result.reason == ZitadelDriftReason.MACHINE_AUTH_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing_resource", "expected_reason"),
    [
        ("org", ZitadelDriftReason.PLATFORM_ORG_MISSING),
        ("admin", ZitadelDriftReason.PLATFORM_ADMIN_MISSING),
        ("project", ZitadelDriftReason.UCP_PROJECT_MISSING),
    ],
)
async def test_verify_zitadel_platform_alignment_detects_org_admin_and_project_drift(
    missing_resource: str,
    expected_reason: ZitadelDriftReason,
) -> None:
    cfg = ZitadelIdentityConfig(
        zitadel_url="http://ucp.localhost:8080",
        machine_key='{"keyId":"1","key":"pem","userId":"2"}',
        platform_org_id="org_live_1",
        platform_admin_id="usr_admin_1",
        ucp_project_id="proj_ucp_1",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/debug/ready":
            return httpx.Response(200, text="ok")
        if request.url.path == "/admin/v1/orgs/_search":
            orgs = (
                [{"id": "org_other", "name": "ZITADEL"}]
                if missing_resource == "org"
                else [{"id": "org_live_1", "name": "Flowwolf"}]
            )
            return httpx.Response(200, json={"result": orgs})
        if request.url.path == "/management/v1/users/usr_admin_1":
            if missing_resource == "admin":
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json={"user": {"id": "usr_admin_1"}})
        if request.url.path == "/management/v1/projects/proj_ucp_1":
            if missing_resource == "project":
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json={"project": {"id": "proj_ucp_1"}})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_zitadel_platform_alignment(
            config=cfg,
            token_provider=_StubAccessTokenProvider(),
            http_client=client,
            ready_timeout_seconds=0.5,
        )
    assert result.aligned is False
    assert result.reason == expected_reason


@pytest.mark.asyncio
async def test_verify_and_cleanup_non_platform_zitadel_orgs_preserves_platform_and_system_orgs() -> (
    None
):
    cfg = ZitadelIdentityConfig(
        zitadel_url="http://ucp.localhost:8080",
        machine_key='{"keyId":"1","key":"pem","userId":"2"}',
        platform_org_id="org_live_1",
        platform_admin_id="usr_admin_1",
        ucp_project_id="proj_ucp_1",
    )
    deleted_org_ids: list[str] = []
    renamed_org_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/debug/ready":
            return httpx.Response(200, text="ok")
        if request.url.path == "/admin/v1/orgs/_search":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"id": "org_sys", "name": "ZITADEL"},
                        {"id": "org_live_1", "name": "Flowwolf"},
                        {"id": "org_ten_stale", "name": "Acme Tenant"},
                    ]
                },
            )
        if request.url.path == "/management/v1/users/usr_admin_1":
            return httpx.Response(200, json={"user": {"id": "usr_admin_1"}})
        if request.url.path == "/management/v1/projects/proj_ucp_1":
            return httpx.Response(200, json={"project": {"id": "proj_ucp_1"}})
        if request.url.path == "/management/v1/orgs/me" and request.method == "PUT":
            renamed_org_ids.append(request.headers["x-zitadel-orgid"])
            return httpx.Response(200, json={})
        if request.url.path.startswith("/admin/v1/orgs/") and request.method == "DELETE":
            deleted_org_ids.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        return httpx.Response(404)

    provider = _StubAccessTokenProvider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        alignment = await verify_zitadel_platform_alignment(
            config=cfg,
            token_provider=provider,
            http_client=client,
            ready_timeout_seconds=0.5,
        )
        assert alignment.aligned is True
        assert alignment.access_token == provider.issued_bearer
        removed = await cleanup_non_platform_zitadel_orgs(
            http_client=client,
            zitadel_url=cfg.zitadel_url,
            access_token=alignment.access_token or "",
            platform_org_id=cfg.platform_org_id,
            all_orgs=alignment.all_orgs,
        )

    assert removed == 1
    assert renamed_org_ids == ["org_ten_stale"]
    assert deleted_org_ids == ["org_ten_stale"]


def test_package_json_reset_and_infra_up_use_host_seed_and_start_identity_before_cleanup() -> None:
    repo_root = find_repo_root(Path(__file__).resolve())
    pkg = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    scripts: dict[str, str] = pkg["scripts"]

    assert "db-seed" not in scripts["infra:up"]
    assert "pnpm db:seed" in scripts["infra:up"]

    for reset_script in ("infra-reset", "infra-reset:edi", "ucp-reset", "soft-reset"):
        cmd = scripts[reset_script]
        assert cmd.index("pnpm infra:start-identity") < cmd.index("pnpm infra:clean-identity-org")
