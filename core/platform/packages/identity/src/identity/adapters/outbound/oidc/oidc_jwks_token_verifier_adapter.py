"""Generic Multi-Issuer OIDC JWKS Token Verifier (Invariant 1 — Zero IdP Lock-In).

Works identically with Casdoor, Logto, Ory Hydra, Keycloak, Auth0, AWS Cognito, Okta,
Microsoft Entra ID, and Zitadel using strictly standard OIDC / RFC 7519 claims.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx
import jwt
import structlog
from jwt import PyJWK, PyJWKSet
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, HttpStatusError, create_http_client

from identity.domain.dtos import TrustedIssuerDTO
from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.domain.identity_context import TokenClaims
from identity.ports.outbound.tenant_hierarchy_port import GlobalAuthzCatalogPort
from identity.ports.outbound.token_verifier_port import TokenValidationError, TokenVerifierPort

logger = structlog.get_logger(__name__)

_SUPPORTED_SIGNING_ALGS: tuple[str, ...] = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


@dataclass(frozen=True, kw_only=True)
class OidcTokenVerifierOptions:
    """Configuration for the provider-agnostic multi-issuer OIDC JWKS verifier."""

    default_issuer: str = ""
    default_jwks_uri: str = ""
    default_audiences: tuple[str, ...] = ()
    default_jwks_host_header: str | None = None
    allow_private_ips: bool = False
    jwks_timeout_seconds: float = 5.0


class OidcJwksTokenVerifierAdapter(TokenVerifierPort):
    """Verifies JWTs from any registered OIDC issuer via cached JWKS with singleflight refresh."""

    def __init__(
        self,
        *,
        options: OidcTokenVerifierOptions,
        global_catalog: GlobalAuthzCatalogPort | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self._options = options
        self._catalog = global_catalog
        self._client = http_client or HttpClient(
            create_http_client(timeout=httpx.Timeout(options.jwks_timeout_seconds, connect=3.0)),
            allow_private_ips=options.allow_private_ips,
        )
        # Cached JWKS keyed by normalized issuer URL -> {kid: PyJWK}
        self._keys_by_issuer: dict[str, dict[str, PyJWK]] = {}
        # Singleflight locks per issuer to prevent JWKS thundering herds on key rotation
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    async def verify_result(self, token: str) -> Result[TokenClaims, IdentityError]:
        """First-class Result-returning verification for standard OIDC bearer JWTs."""
        try:
            header = jwt.get_unverified_header(token)
            unverified_payload = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_exp": False,
                },
            )
        except (jwt.PyJWTError, ValueError) as exc:
            logger.error("oidc_jwt_header_parse_failed", error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message=f"Malformed JWT: {exc}",
                )
            )

        raw_iss = unverified_payload.get("iss")
        if not isinstance(raw_iss, str) or not raw_iss.strip():
            logger.error("oidc_jwt_missing_issuer")
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message="JWT missing required 'iss' claim.",
                )
            )

        normalized_iss = raw_iss.strip().rstrip("/")
        issuer_cfg = self._resolve_trusted_issuer(normalized_iss)
        if issuer_cfg is None or not issuer_cfg.is_active:
            logger.error("oidc_jwt_untrusted_issuer", issuer=normalized_iss)
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.UNTRUSTED_ISSUER,
                    message=f"Untrusted token issuer: {normalized_iss}",
                    details={"issuer": normalized_iss},
                )
            )

        kid = header.get("kid")
        kid_str = str(kid) if isinstance(kid, str) and kid else None
        key_res = await self._resolve_signing_key(issuer_cfg, kid_str)
        if key_res.is_err:
            return Result.fail(key_res.unwrap_err())
        signing_key = key_res.unwrap()

        allowed_auds = {a for a in issuer_cfg.allowed_audiences if a}

        try:
            raw_claims: JsonDict = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(_SUPPORTED_SIGNING_ALGS),
                issuer=raw_iss,
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            logger.error("oidc_jwt_expired", issuer=normalized_iss, error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.TOKEN_EXPIRED,
                    message="Token has expired.",
                )
            )
        except jwt.PyJWTError as exc:
            logger.error(
                "oidc_jwt_verification_failed",
                issuer=normalized_iss,
                kid=kid_str,
                error=str(exc),
            )
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message=f"Token verification failed: {exc}",
                )
            )

        if allowed_auds and not self._matches_allowed_audience(raw_claims, allowed_auds):
            logger.error(
                "oidc_jwt_invalid_audience",
                issuer=normalized_iss,
                aud=raw_claims.get("aud"),
                azp=raw_claims.get("azp"),
            )
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message="Token audience/azp is not allowed for this issuer.",
                )
            )

        return self._build_standard_claims(raw_claims)

    async def verify(self, token: str) -> TokenClaims:
        """Legacy TokenVerifierPort method delegating to `verify_result`."""
        res = await self.verify_result(token)
        if res.is_err:
            raise TokenValidationError(res.unwrap_err().message)
        return res.unwrap()

    def _resolve_trusted_issuer(self, normalized_iss: str) -> TrustedIssuerDTO | None:
        if self._catalog is not None:
            from_catalog = self._catalog.get_trusted_issuer(normalized_iss)
            if from_catalog is not None:
                return from_catalog

        default_iss = self._options.default_issuer.strip().rstrip("/")
        if default_iss and normalized_iss == default_iss:
            jwks_uri = self._options.default_jwks_uri.strip() or f"{default_iss}/.well-known/jwks"
            return TrustedIssuerDTO(
                issuer=default_iss,
                jwks_uri=jwks_uri,
                allowed_audiences=self._options.default_audiences,
                jwks_host_header=self._options.default_jwks_host_header,
                is_active=True,
            )
        return None

    async def _resolve_signing_key(
        self,
        issuer_cfg: TrustedIssuerDTO,
        kid: str | None,
    ) -> Result[PyJWK, IdentityError]:
        issuer_key = issuer_cfg.issuer.rstrip("/")
        cached = self._keys_by_issuer.get(issuer_key, {})
        found = self._pick_key(cached, kid)
        if found is not None:
            return Result.ok(found)

        lock = self._refresh_locks.setdefault(issuer_key, asyncio.Lock())
        async with lock:
            # Double-check after acquiring singleflight lock
            cached = self._keys_by_issuer.get(issuer_key, {})
            found = self._pick_key(cached, kid)
            if found is not None:
                return Result.ok(found)

            fetched_res = await self._fetch_jwks(issuer_cfg)
            if fetched_res.is_err:
                return Result.fail(fetched_res.unwrap_err())
            key_map = fetched_res.unwrap()
            self._keys_by_issuer[issuer_key] = key_map

            found = self._pick_key(key_map, kid)
            if found is None:
                logger.error(
                    "oidc_jwks_kid_not_found",
                    issuer=issuer_key,
                    kid=kid,
                    available_kids=sorted(key_map.keys()),
                )
                return Result.fail(
                    IdentityError(
                        code=IdentityErrorCode.INVALID_TOKEN,
                        message=f"Signing key '{kid}' not found in JWKS for issuer '{issuer_key}'.",
                    )
                )
            return Result.ok(found)

    @staticmethod
    def _pick_key(key_map: Mapping[str, PyJWK], kid: str | None) -> PyJWK | None:
        if not key_map:
            return None
        if kid and kid in key_map:
            return key_map[kid]
        if kid is None and len(key_map) == 1:
            return next(iter(key_map.values()))
        return None

    async def _fetch_jwks(
        self, issuer_cfg: TrustedIssuerDTO
    ) -> Result[dict[str, PyJWK], IdentityError]:
        headers: dict[str, str] = {}
        if issuer_cfg.jwks_host_header:
            headers["Host"] = issuer_cfg.jwks_host_header

        jwks_uri = issuer_cfg.jwks_uri
        if not jwks_uri:
            disc_res = await self._discover_jwks_uri(issuer_cfg.issuer, headers)
            if disc_res.is_err:
                return Result.fail(disc_res.unwrap_err())
            jwks_uri = disc_res.unwrap()

        try:
            response = await self._client.get(jwks_uri, headers=headers)
            response.raise_for_status()
            body = response.json()
        except (HttpError, HttpStatusError, ValueError) as exc:
            logger.error("oidc_jwks_fetch_failed", jwks_uri=jwks_uri, error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message=f"Failed to fetch JWKS from '{jwks_uri}': {exc}",
                )
            )

        if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
            logger.error("oidc_jwks_invalid_payload", jwks_uri=jwks_uri)
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message="JWKS endpoint returned invalid JSON payload.",
                )
            )

        jwk_set = PyJWKSet.from_dict(body)
        key_map: dict[str, PyJWK] = {}
        for idx, jwk in enumerate(jwk_set.keys):
            key_id = jwk.key_id or f"default_{idx}"
            key_map[key_id] = jwk
        return Result.ok(key_map)

    async def _discover_jwks_uri(
        self, issuer: str, headers: dict[str, str]
    ) -> Result[str, IdentityError]:
        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            response = await self._client.get(discovery_url, headers=headers)
            response.raise_for_status()
            doc = response.json()
        except (HttpError, HttpStatusError, ValueError) as exc:
            logger.error("oidc_discovery_failed", discovery_url=discovery_url, error=str(exc))
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message=f"OIDC discovery failed for '{issuer}': {exc}",
                )
            )

        jwks_uri = doc.get("jwks_uri") if isinstance(doc, dict) else None
        if not isinstance(jwks_uri, str) or not jwks_uri.strip():
            logger.error("oidc_discovery_missing_jwks_uri", discovery_url=discovery_url)
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message=f"OIDC discovery document missing jwks_uri for '{issuer}'.",
                )
            )
        return Result.ok(jwks_uri.strip())

    @staticmethod
    def _matches_allowed_audience(raw_claims: JsonDict, allowed_auds: set[str]) -> bool:
        aud_raw = raw_claims.get("aud")
        if isinstance(aud_raw, str) and aud_raw in allowed_auds:
            return True
        if isinstance(aud_raw, list):
            for entry in aud_raw:
                if isinstance(entry, str) and entry in allowed_auds:
                    return True
        # Standard OIDC Core §2 Authorized Party (azp) for multi-realm shared OAuth clients
        azp_raw = raw_claims.get("azp")
        return isinstance(azp_raw, str) and azp_raw in allowed_auds

    @staticmethod
    def _parse_amr(raw_amr: object) -> tuple[str, ...]:
        if isinstance(raw_amr, Sequence) and not isinstance(raw_amr, (str, bytes)):
            return tuple(str(item) for item in raw_amr if item)
        if isinstance(raw_amr, str) and raw_amr.strip():
            return (raw_amr.strip(),)
        return ()

    @staticmethod
    def _parse_scopes(raw_scope: object) -> frozenset[str] | None:
        if isinstance(raw_scope, str) and raw_scope.strip():
            return frozenset(part for part in raw_scope.split() if part)
        if isinstance(raw_scope, Sequence) and not isinstance(raw_scope, (str, bytes)):
            return frozenset(str(part) for part in raw_scope if part)
        return None

    @staticmethod
    def _extract_idp_realm(raw_claims: JsonDict, aud: str | list[str]) -> str | None:
        owner_raw = raw_claims.get("owner")
        if isinstance(owner_raw, str) and owner_raw.strip():
            return owner_raw.strip()
        azp_raw = raw_claims.get("azp")
        if not isinstance(azp_raw, str) or not azp_raw:
            return None
        prefix = f"{azp_raw}-org-"
        aud_candidates = [aud] if isinstance(aud, str) else list(aud)
        for candidate in aud_candidates:
            if candidate.startswith(prefix) and len(candidate) > len(prefix):
                return candidate[len(prefix) :]
        return None

    @classmethod
    def _build_standard_claims(cls, raw_claims: JsonDict) -> Result[TokenClaims, IdentityError]:
        sub = raw_claims.get("sub")
        iss = raw_claims.get("iss")
        aud_raw = raw_claims.get("aud")
        exp_raw = raw_claims.get("exp")

        if not isinstance(sub, str) or not isinstance(iss, str) or not isinstance(exp_raw, int):
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.INVALID_TOKEN,
                    message="JWT missing required standard claims (sub, iss, exp).",
                )
            )

        if isinstance(aud_raw, str):
            aud: str | list[str] = aud_raw
        elif isinstance(aud_raw, list):
            aud = [str(item) for item in aud_raw]
        else:
            aud = ""

        iat_raw = raw_claims.get("iat")
        iat = iat_raw if isinstance(iat_raw, int) else None

        jti_raw = raw_claims.get("jti")
        jti = jti_raw if isinstance(jti_raw, str) and jti_raw else None

        email_raw = raw_claims.get("email")
        email = (
            email_raw.strip().lower() if isinstance(email_raw, str) and email_raw.strip() else None
        )

        email_verified_raw = raw_claims.get("email_verified")
        if not isinstance(email_verified_raw, bool):
            email_verified_raw = raw_claims.get("emailVerified")
        email_verified = bool(email_verified_raw) if isinstance(email_verified_raw, bool) else False

        # Standard realm/owner mapping (Casdoor uses "owner" or shared-app aud "<client>-org-<realm>")
        idp_realm = cls._extract_idp_realm(raw_claims, aud)

        acr_raw = raw_claims.get("acr")
        acr = acr_raw.strip() if isinstance(acr_raw, str) and acr_raw.strip() else None
        amr = cls._parse_amr(raw_claims.get("amr"))

        # RFC 8693 actor claim for audited break-glass impersonation
        act_raw = raw_claims.get("act")
        impersonator_sub: str | None = None
        ticket_id: str | None = None
        if isinstance(act_raw, Mapping):
            act_sub = act_raw.get("sub")
            if isinstance(act_sub, str) and act_sub.strip():
                impersonator_sub = act_sub.strip()
            act_ticket = act_raw.get("ticket_id")
            if isinstance(act_ticket, str) and act_ticket.strip():
                ticket_id = act_ticket.strip()

        scopes = cls._parse_scopes(raw_claims.get("scope") or raw_claims.get("scp"))

        return Result.ok(
            TokenClaims(
                sub=sub,
                iss=iss,
                aud=aud,
                exp=exp_raw,
                iat=iat,
                jti=jti,
                email=email,
                email_verified=email_verified,
                idp_realm=idp_realm,
                acr=acr,
                amr=amr,
                impersonator_subject=impersonator_sub,
                impersonation_ticket_id=ticket_id,
                token_scopes=scopes,
                raw_claims=raw_claims,
            )
        )


__all__ = ["OidcJwksTokenVerifierAdapter", "OidcTokenVerifierOptions"]
