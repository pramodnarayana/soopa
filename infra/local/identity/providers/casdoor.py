"""Casdoor Local Identity Provider Bootstrap Plugin.

Implements `LocalIdentityProviderModule.bootstrap(*, root_dir: Path, reset: bool) -> dict[str, str]`.
Provisions the 3-Realm Hybrid Casdoor topology (`soopa-platform`, `soopa-global`,
`org_demo_enterprise`) and shared applications with minimal `JWT-Custom` tokens (<600B).
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import httpx
import structlog
from dotenv import load_dotenv, set_key

from identity.adapters.outbound.casdoor.constants import (
    CASDOOR_MINIMAL_TOKEN_FIELDS,
    CasdoorEndpoint,
    CasdoorRealm,
    CasdoorTokenFormat,
)

logger = structlog.get_logger(__name__)

DOCKER_BIN = shutil.which("docker") or "docker"
CASDOOR_BASE_URL = "http://localhost:8080"
CASDOOR_BUILT_IN_ADMIN_USER = "admin"
DEFAULT_CASDOOR_ADMIN_PASSWORD = "Password1!"  # noqa: S105 - Local development bootstrap password only
DEMO_ENTERPRISE_REALM = "org_demo_enterprise"


def _update_env_file(env_path: Path, updates: Mapping[str, str]) -> None:
    """Update key=value pairs in `.env` via python-dotenv while preserving comments and layout."""
    if not env_path.exists():
        example_path = env_path.parent / ".env.example"
        if example_path.exists():
            env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.write_text("", encoding="utf-8")

    for key, value in updates.items():
        set_key(env_path, key, value, quote_mode="auto", encoding="utf-8")


def _wait_for_casdoor_health(base_url: str, *, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}{CasdoorEndpoint.HEALTH.value}"
    logger.info("casdoor_bootstrap_waiting_for_health", url=health_url)
    with httpx.Client(timeout=3.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = client.get(health_url)
                if resp.status_code == 200:
                    logger.info("casdoor_bootstrap_healthy", url=health_url)
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1.5)
    raise TimeoutError(f"Casdoor did not become healthy at {health_url} within {timeout_seconds}s")


def _login_builtin_admin(
    client: httpx.Client,
    *,
    base_url: str,
    admin_password: str,
) -> str:
    login_url = f"{base_url.rstrip('/')}{CasdoorEndpoint.LOGIN.value}"
    candidates = [admin_password]
    if "123" not in candidates:
        candidates.append("123")

    for pwd in candidates:
        resp = client.post(
            login_url,
            json={
                "application": "app-built-in",
                "organization": CasdoorRealm.BUILT_IN.value,
                "username": CASDOOR_BUILT_IN_ADMIN_USER,
                "password": pwd,
                "type": "login",
            },
        )
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict) and body.get("status") == "ok":
                logger.info("casdoor_admin_authenticated")
                return ""
    raise RuntimeError(
        "Failed to authenticate Casdoor built-in admin. Check CASDOOR_ADMIN_PASSWORD."
    )


def _casdoor_request(
    client: httpx.Client,
    method: str,
    base_url: str,
    endpoint: str,
    *,
    bearer_token: str,
    params: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
) -> dict[str, object]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    resp = client.request(
        method,
        f"{base_url.rstrip('/')}{endpoint}",
        params=params,
        json=json_body,
        headers=headers,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected Casdoor response for {endpoint}: {data!r}")
    if data.get("status") == "error":
        raise RuntimeError(f"Casdoor API error on {endpoint}: {data.get('msg')}")
    return data


def _ensure_organization(
    client: httpx.Client,
    *,
    base_url: str,
    bearer_token: str,
    name: str,
    display_name: str,
    default_application: str = "soopa-dashboard",
) -> None:
    existing = _casdoor_request(
        client,
        "GET",
        base_url,
        CasdoorEndpoint.GET_ORGANIZATION.value,
        bearer_token=bearer_token,
        params={"id": f"admin/{name}"},
    )
    existing_org = existing.get("data")
    if isinstance(existing_org, dict):
        if existing_org.get("defaultApplication") != default_application:
            org_doc = dict(existing_org)
            org_doc["defaultApplication"] = default_application
            _casdoor_request(
                client,
                "POST",
                base_url,
                CasdoorEndpoint.UPDATE_ORGANIZATION.value,
                bearer_token=bearer_token,
                params={"id": f"admin/{name}"},
                json_body=org_doc,
            )
            logger.info(
                "casdoor_org_updated",
                organization=name,
                default_application=default_application,
            )
        else:
            logger.info("casdoor_org_exists", organization=name)
        return

    _casdoor_request(
        client,
        "POST",
        base_url,
        CasdoorEndpoint.ADD_ORGANIZATION.value,
        bearer_token=bearer_token,
        json_body={
            "owner": "admin",
            "name": name,
            "displayName": display_name,
            "defaultApplication": default_application,
            "passwordType": "bcrypt",
            "passwordSalt": "",
            "defaultAvatar": "https://cdn.casbin.org/img/casbin.svg",
            "initScore": 0,
            "languages": ["en"],
            "enableSoftDeletion": True,
        },
    )
    logger.info(
        "casdoor_org_created",
        organization=name,
        default_application=default_application,
    )


def _ensure_application(
    client: httpx.Client,
    *,
    base_url: str,
    bearer_token: str,
    name: str,
    display_name: str,
    redirect_uris: list[str],
    organization: str,
    is_shared: bool,
    grant_types: list[str],
    enable_sign_up: bool,
    enable_password: bool = True,
    enable_webauthn: bool = True,
) -> tuple[str, str]:
    existing = _casdoor_request(
        client,
        "GET",
        base_url,
        CasdoorEndpoint.GET_APPLICATION.value,
        bearer_token=bearer_token,
        params={"id": f"admin/{name}"},
    )
    existing_data = existing.get("data")
    if isinstance(existing_data, dict) and existing_data.get("clientId"):
        app_doc = dict(existing_data)
        app_doc["organization"] = organization
        app_doc["tokenFormat"] = CasdoorTokenFormat.JWT_CUSTOM.value
        app_doc["tokenFields"] = list(CASDOOR_MINIMAL_TOKEN_FIELDS)
        app_doc["redirectUris"] = redirect_uris
        app_doc["isShared"] = is_shared
        app_doc["enablePassword"] = enable_password
        app_doc["enableSignUp"] = enable_sign_up
        app_doc["enableWebAuthn"] = enable_webauthn
        app_doc["grantTypes"] = grant_types
        _casdoor_request(
            client,
            "POST",
            base_url,
            CasdoorEndpoint.UPDATE_APPLICATION.value,
            bearer_token=bearer_token,
            params={"id": f"admin/{name}"},
            json_body=app_doc,
        )
        logger.info("casdoor_app_updated", application=name, grant_types=grant_types)
        return str(app_doc["clientId"]), str(app_doc.get("clientSecret") or "")

    client_id = f"soopa_{name.replace('-', '_')}_{secrets.token_hex(6)}"
    client_secret = secrets.token_hex(24)
    _casdoor_request(
        client,
        "POST",
        base_url,
        CasdoorEndpoint.ADD_APPLICATION.value,
        bearer_token=bearer_token,
        json_body={
            "owner": "admin",
            "name": name,
            "displayName": display_name,
            "organization": organization,
            "cert": "cert-built-in",
            "enablePassword": enable_password,
            "enableSignUp": enable_sign_up,
            "enableCodeSignin": False,
            "enableWebAuthn": enable_webauthn,
            "isShared": is_shared,
            "clientId": client_id,
            "clientSecret": client_secret,
            "redirectUris": redirect_uris,
            "tokenFormat": CasdoorTokenFormat.JWT_CUSTOM.value,
            "tokenFields": list(CASDOOR_MINIMAL_TOKEN_FIELDS),
            "expireInHours": 1,
            "refreshExpireInHours": 24,
            "grantTypes": grant_types,
        },
    )
    logger.info("casdoor_app_created", application=name, client_id=client_id)
    return client_id, client_secret


def _ensure_user(
    client: httpx.Client,
    *,
    base_url: str,
    bearer_token: str,
    organization: str,
    username: str,
    email: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
) -> str:
    existing = _casdoor_request(
        client,
        "GET",
        base_url,
        CasdoorEndpoint.GET_USER.value,
        bearer_token=bearer_token,
        params={"id": f"{organization}/{username}"},
    )
    existing_data = existing.get("data")
    if isinstance(existing_data, dict) and existing_data.get("id"):
        logger.info("casdoor_user_exists", organization=organization, username=username)
        return str(existing_data["id"])

    _casdoor_request(
        client,
        "POST",
        base_url,
        CasdoorEndpoint.ADD_USER.value,
        bearer_token=bearer_token,
        json_body={
            "owner": organization,
            "name": username,
            "displayName": display_name,
            "email": email,
            "emailVerified": True,
            "password": password,
            "type": "normal-user",
            "isAdmin": is_admin,
            "isForbidden": False,
        },
    )
    created = _casdoor_request(
        client,
        "GET",
        base_url,
        CasdoorEndpoint.GET_USER.value,
        bearer_token=bearer_token,
        params={"id": f"{organization}/{username}"},
    )
    created_data = created.get("data")
    if not isinstance(created_data, dict) or not created_data.get("id"):
        raise RuntimeError(f"Casdoor created user {organization}/{username} without ID")
    logger.info(
        "casdoor_user_created",
        organization=organization,
        username=username,
        user_id=str(created_data["id"]),
    )
    return str(created_data["id"])


def _start_casdoor_containers(root_dir: Path, *, reset: bool) -> None:
    compose_cmd = [
        DOCKER_BIN,
        "compose",
        "--env-file",
        ".env",
        "--env-file",
        "versions.env",
        "-f",
        "docker-compose.identity.yml",
    ]
    if reset:
        logger.info("casdoor_bootstrap_resetting_containers")
        subprocess.run(  # noqa: S603 - Trusted local docker compose invocation
            [*compose_cmd, "down", "-v"],
            cwd=root_dir,
            check=True,
        )

    logger.info("casdoor_bootstrap_starting_containers")
    subprocess.run(  # noqa: S603 - Trusted local docker compose invocation
        [*compose_cmd, "up", "-d", "--wait"],
        cwd=root_dir,
        check=True,
    )


def bootstrap(*, root_dir: Path, reset: bool) -> dict[str, str]:
    """Start local Casdoor, provision realms/apps/users, and sync canonical `.env` keys."""
    env_path = root_dir / ".env"
    if not env_path.exists():
        example_path = root_dir / ".env.example"
        if example_path.exists():
            env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    load_dotenv(env_path)

    base_url = os.getenv("IDENTITY_API_URL", CASDOOR_BASE_URL).strip() or CASDOOR_BASE_URL
    if "ucp.localhost" in base_url:
        base_url = CASDOOR_BASE_URL
    admin_password = os.getenv("CASDOOR_ADMIN_PASSWORD", DEFAULT_CASDOOR_ADMIN_PASSWORD)
    company_domain = os.getenv("COMPANY_DOMAIN", "flowwolf.io")
    platform_admin_email = os.getenv("IDENTITY_PLATFORM_ADMIN_EMAIL", f"admin@{company_domain}")
    platform_admin_password = os.getenv(
        "IDENTITY_PLATFORM_ADMIN_PASSWORD",
        os.getenv("IDENTITY_DEFAULT_USER_PASSWORD", DEFAULT_CASDOOR_ADMIN_PASSWORD),
    )
    default_user_password = os.getenv(
        "IDENTITY_DEFAULT_USER_PASSWORD", DEFAULT_CASDOOR_ADMIN_PASSWORD
    )

    _start_casdoor_containers(root_dir, reset=reset)
    _wait_for_casdoor_health(base_url)

    with httpx.Client(timeout=10.0) as client:
        bearer_token = _login_builtin_admin(
            client,
            base_url=base_url,
            admin_password=admin_password,
        )

        _ensure_organization(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name=CasdoorRealm.PLATFORM.value,
            display_name="Soopa Platform Operators",
            default_application="soopa-platform-admin",
        )
        _ensure_organization(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name=CasdoorRealm.GLOBAL.value,
            display_name="Soopa Global (Individuals & Standard Companies)",
            default_application="soopa-dashboard",
        )
        _ensure_organization(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name=DEMO_ENTERPRISE_REALM,
            display_name="Demo Enterprise Dedicated SSO Realm",
            default_application="soopa-dashboard",
        )

        # 1. Customer SPA (B2C Individuals, SMBs, & Enterprise SSO) — OAuth 2.1 Auth Code + PKCE only
        dashboard_client_id, dashboard_client_secret = _ensure_application(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name="soopa-dashboard",
            display_name="Soopa Unified Dashboard",
            redirect_uris=[
                "http://localhost:5173/callback",
                "http://localhost:3000/callback",
                "http://localhost:8080/callback",
            ],
            organization=CasdoorRealm.BUILT_IN.value,
            is_shared=True,
            grant_types=["authorization_code", "refresh_token"],
            enable_sign_up=True,
            enable_password=True,
            enable_webauthn=True,
        )
        # 2. Platform Operator Console — isolated to soopa-platform with self-signup strictly disabled
        platform_console_client_id, _ = _ensure_application(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name="soopa-platform-admin",
            display_name="Soopa Platform Operator Console",
            redirect_uris=[
                "http://localhost:5173/callback",
                "http://localhost:3000/callback",
            ],
            organization=CasdoorRealm.PLATFORM.value,
            is_shared=False,
            grant_types=["authorization_code", "refresh_token"],
            enable_sign_up=False,
            enable_password=True,
            enable_webauthn=True,
        )
        # 3. Backend Admin & M2M Service Client — strictly client_credentials, zero interactive login
        m2m_client_id, m2m_client_secret = _ensure_application(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            name="soopa-api-m2m",
            display_name="Soopa Backend Admin & M2M",
            redirect_uris=[],
            organization=CasdoorRealm.BUILT_IN.value,
            is_shared=True,
            grant_types=["client_credentials"],
            enable_sign_up=False,
            enable_password=False,
            enable_webauthn=False,
        )

        platform_admin_id = _ensure_user(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            organization=CasdoorRealm.PLATFORM.value,
            username="platform_admin",
            email=platform_admin_email,
            display_name="Platform Admin",
            password=platform_admin_password,
            is_admin=True,
        )
        _ensure_user(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            organization=CasdoorRealm.GLOBAL.value,
            username="demo_smb_admin",
            email="demo@acme.local",
            display_name="Acme SMB Admin",
            password=default_user_password,
        )
        _ensure_user(
            client,
            base_url=base_url,
            bearer_token=bearer_token,
            organization=CasdoorRealm.GLOBAL.value,
            username="solo_consumer",
            email="solo@example.com",
            display_name="Solo Individual User",
            password=default_user_password,
        )

    env_updates = {
        "IDENTITY_PROVIDER": "casdoor",
        "IDENTITY_API_URL": base_url,
        "IDENTITY_ISSUER": base_url,
        "IDENTITY_JWKS_URL": f"{base_url}{CasdoorEndpoint.JWKS.value}",
        "IDENTITY_AUTHORIZATION_URL": f"{base_url}/login/oauth/authorize",
        "IDENTITY_TOKEN_URL": f"{base_url}{CasdoorEndpoint.OAUTH_TOKEN.value}",
        "IDENTITY_USERINFO_URL": f"{base_url}/api/userinfo",
        "IDENTITY_PLATFORM_REALM": CasdoorRealm.PLATFORM.value,
        "IDENTITY_GLOBAL_REALM": CasdoorRealm.GLOBAL.value,
        "IDENTITY_PLATFORM_ORG_ID": CasdoorRealm.PLATFORM.value,
        "IDENTITY_PLATFORM_ADMIN_ID": platform_admin_id,
        "IDENTITY_OAUTH_CLIENT_ID": dashboard_client_id,
        "IDENTITY_OAUTH_CLIENT_SECRET": dashboard_client_secret,
        "IDENTITY_PLATFORM_ADMIN_CLIENT_ID": platform_console_client_id,
        "IDENTITY_SHARED_APP_REALM_DELIMITER": "-org-",
        "IDENTITY_UCP_WEB_CLIENT_ID": dashboard_client_id,
        "VITE_IDENTITY_UCP_WEB_CLIENT_ID": dashboard_client_id,
        "VITE_IDENTITY_API_URL": base_url,
        "IDENTITY_ADMIN_CLIENT_ID": m2m_client_id,
        "IDENTITY_ADMIN_CLIENT_SECRET": m2m_client_secret,
        "IDENTITY_AUDIENCE": f"{dashboard_client_id},{platform_console_client_id},{m2m_client_id}",
        "IDENTITY_ALLOW_PRIVATE_IPS": "true",
    }
    _update_env_file(env_path, env_updates)
    logger.info(
        "casdoor_bootstrap_completed",
        issuer=base_url,
        dashboard_client_id=dashboard_client_id,
    )

    subprocess.run(  # noqa: S603 - Trusted local Python interpreter invocation
        [sys.executable, str(root_dir / "infra" / "local" / "scripts" / "print_credentials.py")],
        cwd=root_dir,
        check=False,
    )
    return env_updates


__all__ = ["bootstrap"]
