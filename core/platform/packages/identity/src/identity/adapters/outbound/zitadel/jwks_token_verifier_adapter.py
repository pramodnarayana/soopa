import asyncio
import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
import jwt
import structlog
from jwt import PyJWK, PyJWKClient
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, HttpStatusError, create_http_client

from identity.adapters.outbound.zitadel.constants import ZitadelClaims
from identity.domain.identity_context import PLATFORM_TENANT_ID, TokenClaims
from identity.ports.outbound.token_verifier_port import TokenValidationError, TokenVerifierPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ZitadelTokenVerifierOptions:
    issuer: str
    audience: str | list[str]
    jwks_url: str | None = None
    platform_org_id: str | None = None
    # Optional Host header override for JWKS fetching.
    # Use this when the JWKS URL points to an internal address (e.g. Cloud Map)
    # but Zitadel requires the Host header to match its external domain for
    # instance routing. Keeps JWKS traffic internal (no ALB hairpin) while
    # satisfying Zitadel's host-header validation.
    jwks_host_header: str | None = None
    allow_private_ips: bool = False


class ZitadelTokenVerifierAdapter(TokenVerifierPort):
    def __init__(
        self,
        options: ZitadelTokenVerifierOptions,
        client: HttpClient | None = None,
    ) -> None:
        self._options = options
        self._jwks_url = options.jwks_url or f"{options.issuer}/oauth/v2/keys"
        jwks_headers: dict[str, str] | None = None
        if options.jwks_host_header:
            jwks_headers = {"Host": options.jwks_host_header}
        self._jwks_client = PyJWKClient(self._jwks_url, headers=jwks_headers)
        self._client: HttpClient = client or HttpClient(
            create_http_client(timeout=httpx.Timeout(5.0, connect=3.0)),
            allow_private_ips=options.allow_private_ips,
        )
        # Thread-safe async cache for userinfo to prevent network calls on every request
        # Format: {jti: (userinfo_dict, timestamp)}
        self._userinfo_cache: dict[str, tuple[JsonDict, float]] = {}

    @property
    def jwks_url(self) -> str:
        """The URL used to fetch JWKS (may be an internal Cloud Map address)."""
        return self._jwks_url

    @property
    def jwks_host_header(self) -> str | None:
        """The Host header sent with JWKS requests, or None if not overridden."""
        return self._options.jwks_host_header

    async def verify(self, token: str) -> TokenClaims:
        payload, raw_claims = await self._decode_jwt_payload(token)
        await self._enrich_missing_project_roles(token, payload)
        self._map_platform_org_sentinel(payload)
        self._populate_normalized_tenant_claims(payload)

        try:
            return self._to_token_claims(payload, raw_claims)
        except Exception as e:
            logger.exception("token_claims_validation_failed", exc_info=e)
            raise TokenValidationError(f"Invalid token claims: {e}") from e

    async def _decode_jwt_payload(self, token: str) -> tuple[dict[str, object], JsonDict]:
        try:
            signing_key = await self._get_signing_key(token)
            raw_claims: JsonDict = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._options.audience,
                issuer=self._options.issuer,
            )
            decoded: dict[str, object] = dict(raw_claims)
            return decoded, raw_claims
        except jwt.PyJWTError as e:
            logger.exception("jwt_decode_failed", exc_info=e)
            raise TokenValidationError(str(e)) from e
        except Exception as e:
            logger.exception("signing_key_or_jwt_decode_failed", exc_info=e)
            raise TokenValidationError(str(e)) from e

    async def _enrich_missing_project_roles(self, token: str, payload: dict[str, object]) -> None:
        if ZitadelClaims.PROJECT_ROLES in payload:
            return
        raw_jti = payload.get("jti")
        jti = (
            raw_jti
            if isinstance(raw_jti, str) and raw_jti
            else hashlib.sha256(token.encode()).hexdigest()
        )
        try:
            userinfo = await self._get_cached_userinfo(token, jti)
            payload.update(userinfo)
        except (HttpError, ValueError, TypeError) as e:
            logger.error("failed_to_fetch_userinfo", exc_info=e)

    def _map_platform_org_sentinel(self, payload: dict[str, object]) -> None:
        if not self._options.platform_org_id:
            return
        roles_dict = payload.get(ZitadelClaims.PROJECT_ROLES)
        if not isinstance(roles_dict, dict):
            return
        for orgs in roles_dict.values():
            if isinstance(orgs, dict) and self._options.platform_org_id in orgs:
                orgs[PLATFORM_TENANT_ID] = orgs[self._options.platform_org_id]

    @staticmethod
    def _collect_org_role_map(
        role_map: Mapping[object, object],
        authorized_tenants: set[str],
        tenant_roles: dict[str, list[str]],
        roles: list[str],
    ) -> None:
        for role, orgs in role_map.items():
            if not isinstance(orgs, Mapping):
                continue
            role_str = str(role)
            for org_id in orgs:
                org_str = str(org_id)
                authorized_tenants.add(org_str)
                tenant_roles.setdefault(org_str, []).append(role_str)
                roles.append(role_str)

    @classmethod
    def _populate_normalized_tenant_claims(cls, payload: dict[str, object]) -> None:
        authorized_tenants: set[str] = set()
        tenant_roles: dict[str, list[str]] = {}
        roles: list[str] = []

        tenant_id = payload.get("tenant_id") or payload.get(ZitadelClaims.ORG_ID)
        if tenant_id:
            authorized_tenants.add(str(tenant_id))

        idp_org_id = payload.get(ZitadelClaims.ORG_ID)
        if idp_org_id:
            authorized_tenants.add(str(idp_org_id))

        if ZitadelClaims.PROJECT_ROLES in payload:
            project_roles = payload.get(ZitadelClaims.PROJECT_ROLES)
            if isinstance(project_roles, Mapping):
                cls._collect_org_role_map(project_roles, authorized_tenants, tenant_roles, roles)
        else:
            generic_roles = payload.get("roles")
            if isinstance(generic_roles, Mapping):
                cls._collect_org_role_map(generic_roles, authorized_tenants, tenant_roles, roles)
            elif isinstance(generic_roles, list):
                roles = [str(r) for r in generic_roles]

        payload["tenant_id"] = str(tenant_id) if tenant_id else None
        payload["authorized_tenants"] = authorized_tenants
        payload["tenant_roles"] = tenant_roles
        payload["roles"] = roles

    @staticmethod
    def _to_token_claims(payload: Mapping[str, object], raw_claims: JsonDict) -> TokenClaims:
        sub = payload.get("sub")
        iss = payload.get("iss")
        aud_raw = payload.get("aud")
        exp_raw = payload.get("exp")
        if not isinstance(sub, str) or not isinstance(iss, str) or not isinstance(exp_raw, int):
            raise TypeError("Missing or invalid required JWT claims (sub, iss, exp)")
        if isinstance(aud_raw, str):
            aud: str | list[str] = aud_raw
        elif isinstance(aud_raw, list):
            aud = [str(item) for item in aud_raw]
        else:
            raise TypeError("Invalid JWT audience claim")

        iat_raw = payload.get("iat")
        iat = iat_raw if isinstance(iat_raw, int) else None

        tenant_id_raw = payload.get("tenant_id")
        tenant_id = str(tenant_id_raw) if tenant_id_raw is not None else None

        org_id_raw = payload.get("organization_id")
        organization_id = str(org_id_raw) if org_id_raw is not None else None

        auth_tenants_raw = payload.get("authorized_tenants")
        if isinstance(auth_tenants_raw, (set, list, tuple)):
            authorized_tenants: set[str] = {str(t) for t in auth_tenants_raw}
        else:
            authorized_tenants = set()

        roles_raw = payload.get("roles")
        roles: list[str] = [str(r) for r in roles_raw] if isinstance(roles_raw, list) else []

        perms_raw = payload.get("permissions")
        permissions: list[str] = [str(p) for p in perms_raw] if isinstance(perms_raw, list) else []

        tenant_roles_raw = payload.get("tenant_roles")
        tenant_roles: dict[str, list[str]] = {}
        if isinstance(tenant_roles_raw, Mapping):
            for t_key, r_vals in tenant_roles_raw.items():
                if isinstance(r_vals, list):
                    tenant_roles[str(t_key)] = [str(r) for r in r_vals]

        return TokenClaims(
            sub=sub,
            iss=iss,
            aud=aud,
            exp=exp_raw,
            iat=iat,
            tenant_id=tenant_id,
            organization_id=organization_id,
            authorized_tenants=authorized_tenants,
            roles=roles,
            permissions=permissions,
            tenant_roles=tenant_roles,
            raw_claims=raw_claims,
        )

    async def _get_signing_key(self, token: str) -> PyJWK:
        return await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)

    async def _get_cached_userinfo(self, token: str, jti: str) -> JsonDict:
        now = time.time()

        # Check TTL cache (O(1) access)
        if jti in self._userinfo_cache:
            userinfo, timestamp = self._userinfo_cache[jti]
            if now - timestamp < 3600:
                return userinfo
            del self._userinfo_cache[jti]

        # Fetch from Zitadel asynchronously using shttp HttpClient
        url = f"{self._options.issuer}/oidc/v1/userinfo"
        headers = {"Authorization": f"Bearer {token}"}

        response = await self._client.get(
            url,
            headers=headers,
            allow_private_ips=self._options.allow_private_ips,
        )
        if response.status_code >= 400:
            logger.error(
                "userinfo_request_failed",
                url=url,
                status_code=response.status_code,
            )
            raise HttpStatusError.from_response(response)

        userinfo = response.json()

        if not isinstance(userinfo, dict):
            raise TypeError("userinfo response must be a JSON object")

        # Update cache
        self._userinfo_cache[jti] = (userinfo, now)

        # O(1) eviction for maxsize
        if len(self._userinfo_cache) > 1000:
            oldest_key = next(iter(self._userinfo_cache))
            del self._userinfo_cache[oldest_key]

        return userinfo

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
