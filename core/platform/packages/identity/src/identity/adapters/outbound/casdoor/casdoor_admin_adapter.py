"""Casdoor Admin Adapter implementing the minimal 5-method IdentityProviderAdminPort."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, HttpStatusError, create_http_client

from identity.adapters.outbound.casdoor.constants import (
    CASDOOR_DEFAULT_APPLICATION,
    CasdoorEndpoint,
)
from identity.domain.dtos import EnterpriseSsoConfigDTO, ExternalIdentityRef, RealmRef
from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.ports.outbound.identity_provider_admin_port import IdentityProviderAdminPort

logger = structlog.get_logger(__name__)

_SAFE_USERNAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True, kw_only=True)
class CasdoorAdminOptions:
    """Configuration for Casdoor management API calls (private internal network only)."""

    endpoint: str
    client_id: str
    client_secret: str
    default_organization: str = "soopa-global"
    default_application: str = CASDOOR_DEFAULT_APPLICATION
    allow_private_ips: bool = False
    timeout_seconds: float = 10.0


def _derive_casdoor_username(email: str) -> str:
    local = email.strip().lower().replace("@", "_")
    sanitized = _SAFE_USERNAME_RE.sub("_", local).strip("_")
    return sanitized[:64] or "user"


class CasdoorAdminAdapter(IdentityProviderAdminPort):
    """Implements IdentityProviderAdminPort against Casdoor's HTTP Management API.

    Uses Basic Auth (`client_id:client_secret`) and returns first-class `Result` objects
    for all operational failures (zero uncaught HTTP exceptions on expected errors).
    """

    def __init__(
        self,
        *,
        options: CasdoorAdminOptions,
        http_client: HttpClient | None = None,
    ) -> None:
        self._options = options
        self._base_url = options.endpoint.rstrip("/")
        self._client = http_client or HttpClient(
            create_http_client(timeout=httpx.Timeout(options.timeout_seconds, connect=3.0)),
            allow_private_ips=options.allow_private_ips,
        )
        raw_creds = f"{options.client_id}:{options.client_secret}".encode()
        self._auth_header = f"Basic {base64.b64encode(raw_creds).decode('ascii')}"

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post_json(
        self,
        endpoint: str,
        payload: JsonDict,
        *,
        params: dict[str, str] | None = None,
    ) -> Result[JsonDict, IdentityError]:
        url = f"{self._base_url}{endpoint}"
        try:
            resp = await self._client.post(
                url,
                json=payload,
                params=params,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                logger.error(
                    "casdoor_admin_http_error",
                    endpoint=endpoint,
                    status_code=resp.status_code,
                    response_text=resp.text[:300],
                )
                return Result.fail(
                    IdentityError(
                        code=IdentityErrorCode.IDP_ADMIN_ERROR,
                        message=f"Casdoor returned HTTP {resp.status_code} for {endpoint}.",
                        details={"status_code": resp.status_code, "endpoint": endpoint},
                    )
                )
            data = resp.json()
        except (HttpError, HttpStatusError, ValueError) as exc:
            logger.error("casdoor_admin_request_failed", endpoint=endpoint, error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=f"Casdoor request failed for {endpoint}: {exc}",
                )
            )

        if not isinstance(data, dict):
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=f"Casdoor returned non-object response for {endpoint}.",
                )
            )

        if data.get("status") == "error":
            err_msg = str(data.get("msg") or "Unknown Casdoor API error")
            logger.error("casdoor_admin_api_error", endpoint=endpoint, msg=err_msg)
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=err_msg,
                    details={"endpoint": endpoint},
                )
            )

        return Result.ok(data)

    async def _get_json(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Result[JsonDict, IdentityError]:
        url = f"{self._base_url}{endpoint}"
        try:
            resp = await self._client.get(url, params=params, headers=self._headers())
            if resp.status_code >= 400:
                logger.error(
                    "casdoor_admin_get_http_error",
                    endpoint=endpoint,
                    status_code=resp.status_code,
                )
                return Result.fail(
                    IdentityError(
                        code=IdentityErrorCode.IDP_ADMIN_ERROR,
                        message=f"Casdoor returned HTTP {resp.status_code} for {endpoint}.",
                    )
                )
            data = resp.json()
        except (HttpError, HttpStatusError, ValueError) as exc:
            logger.error("casdoor_admin_get_failed", endpoint=endpoint, error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=f"Casdoor GET failed for {endpoint}: {exc}",
                )
            )

        if not isinstance(data, dict) or data.get("status") == "error":
            msg = str(data.get("msg") if isinstance(data, dict) else "Invalid response")
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=msg,
                )
            )
        return Result.ok(data)

    async def create_user(
        self,
        *,
        realm: str,
        email: str,
        display_name: str,
        initial_password: str | None = None,
    ) -> Result[ExternalIdentityRef, IdentityError]:
        owner = realm.strip() or self._options.default_organization
        username = _derive_casdoor_username(email)

        existing = await self._get_json(
            CasdoorEndpoint.GET_USER.value,
            params={"id": f"{owner}/{username}"},
        )
        if existing.is_ok:
            existing_user = existing.unwrap().get("data")
            if isinstance(existing_user, dict) and existing_user.get("id"):
                return Result.ok(
                    ExternalIdentityRef(
                        idp_issuer=self._base_url,
                        idp_subject=str(existing_user["id"]),
                        idp_realm_name=owner,
                        created=False,
                    )
                )

        payload: JsonDict = {
            "owner": owner,
            "name": username,
            "displayName": display_name.strip() or username,
            "email": email.strip().lower(),
            "emailVerified": True,
            "type": "normal-user",
            "isForbidden": False,
        }
        if initial_password:
            payload["password"] = initial_password

        res = await self._post_json(CasdoorEndpoint.ADD_USER.value, payload)
        if res.is_err:
            return Result.fail(res.unwrap_err())

        fetched = await self._get_json(
            CasdoorEndpoint.GET_USER.value,
            params={"id": f"{owner}/{username}"},
        )
        if fetched.is_err:
            return Result.fail(fetched.unwrap_err())

        user_data = fetched.unwrap().get("data")
        if not isinstance(user_data, dict) or not user_data.get("id"):
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message="Casdoor created user but did not return canonical user ID.",
                )
            )

        return Result.ok(
            ExternalIdentityRef(
                idp_issuer=self._base_url,
                idp_subject=str(user_data["id"]),
                idp_realm_name=owner,
                created=True,
            )
        )

    async def _fetch_user_by_subject(
        self, *, realm: str, external_subject: str
    ) -> Result[JsonDict, IdentityError]:
        res = await self._get_json(
            CasdoorEndpoint.GET_USER.value,
            params={"userId": external_subject, "owner": realm},
        )
        if res.is_err:
            return Result.fail(res.unwrap_err())
        user_data = res.unwrap().get("data")
        if not isinstance(user_data, dict) or not user_data.get("name"):
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message=f"Casdoor user '{external_subject}' not found in realm '{realm}'.",
                )
            )
        return Result.ok(user_data)

    async def update_user(
        self,
        *,
        realm: str,
        external_subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> Result[None, IdentityError]:
        owner = realm.strip() or self._options.default_organization
        fetched = await self._fetch_user_by_subject(realm=owner, external_subject=external_subject)
        if fetched.is_err:
            return Result.fail(fetched.unwrap_err())

        user_doc = dict(fetched.unwrap())
        if email is not None:
            user_doc["email"] = email.strip().lower()
        if display_name is not None:
            user_doc["displayName"] = display_name.strip()

        user_key = f"{owner}/{user_doc['name']}"
        upd = await self._post_json(
            CasdoorEndpoint.UPDATE_USER.value,
            user_doc,
            params={"id": user_key},
        )
        if upd.is_err:
            return Result.fail(upd.unwrap_err())
        return Result.ok(None)

    async def set_user_active(
        self,
        *,
        realm: str,
        external_subject: str,
        active: bool,
    ) -> Result[None, IdentityError]:
        owner = realm.strip() or self._options.default_organization
        fetched = await self._fetch_user_by_subject(realm=owner, external_subject=external_subject)
        if fetched.is_err:
            return Result.fail(fetched.unwrap_err())

        user_doc = dict(fetched.unwrap())
        user_doc["isForbidden"] = not active
        user_key = f"{owner}/{user_doc['name']}"
        upd = await self._post_json(
            CasdoorEndpoint.UPDATE_USER.value,
            user_doc,
            params={"id": user_key},
        )
        if upd.is_err:
            return Result.fail(upd.unwrap_err())
        return Result.ok(None)

    async def delete_user(
        self,
        *,
        realm: str,
        external_subject: str,
    ) -> Result[None, IdentityError]:
        owner = realm.strip() or self._options.default_organization
        fetched = await self._fetch_user_by_subject(realm=owner, external_subject=external_subject)
        if fetched.is_err:
            return Result.fail(fetched.unwrap_err())

        user_doc = dict(fetched.unwrap())
        deleted = await self._post_json(CasdoorEndpoint.DELETE_USER.value, user_doc)
        if deleted.is_err:
            return Result.fail(deleted.unwrap_err())
        return Result.ok(None)

    async def provision_dedicated_enterprise_realm(
        self,
        *,
        slug: str,
        display_name: str,
        sso_config: EnterpriseSsoConfigDTO | None = None,
    ) -> Result[RealmRef, IdentityError]:
        realm_name = f"org_{_SAFE_USERNAME_RE.sub('_', slug.strip().lower()).strip('_')}"
        existing = await self._get_json(
            CasdoorEndpoint.GET_ORGANIZATION.value,
            params={"id": f"admin/{quote(realm_name, safe='')}"},
        )
        if existing.is_ok and isinstance(existing.unwrap().get("data"), dict):
            return Result.ok(
                RealmRef(
                    idp_issuer=self._base_url,
                    realm_name=realm_name,
                    display_name=display_name,
                )
            )

        org_payload: JsonDict = {
            "owner": "admin",
            "name": realm_name,
            "displayName": display_name.strip() or realm_name,
            "defaultApplication": self._options.default_application,
            "passwordType": "bcrypt",
            "enableSoftDeletion": True,
        }
        created = await self._post_json(CasdoorEndpoint.ADD_ORGANIZATION.value, org_payload)
        if created.is_err:
            return Result.fail(created.unwrap_err())

        if sso_config is not None and sso_config.protocol:
            provider_payload: JsonDict = {
                "owner": realm_name,
                "name": f"sso_{realm_name}",
                "displayName": f"{display_name} SSO",
                "category": "SAML" if sso_config.protocol.upper() == "SAML" else "OAuth",
                "type": "SAML" if sso_config.protocol.upper() == "SAML" else "Custom",
                "clientId": sso_config.client_id or "",
                "clientSecret": sso_config.client_secret or "",
                "metadata": sso_config.metadata_url or "",
                "customAuthUrl": sso_config.issuer_url or "",
            }
            prov_res = await self._post_json(CasdoorEndpoint.ADD_PROVIDER.value, provider_payload)
            if prov_res.is_err:
                return Result.fail(prov_res.unwrap_err())

        return Result.ok(
            RealmRef(
                idp_issuer=self._base_url,
                realm_name=realm_name,
                display_name=display_name,
            )
        )


__all__ = ["CasdoorAdminAdapter", "CasdoorAdminOptions"]
