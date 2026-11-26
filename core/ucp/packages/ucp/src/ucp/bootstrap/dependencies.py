from collections.abc import AsyncGenerator
from functools import lru_cache
from urllib.parse import urlparse

from database.provider import DatabaseProvider
from fastapi import Request
from identity.adapters.outbound.oidc.oidc_jwks_token_verifier_adapter import (
    OidcJwksTokenVerifierAdapter,
    OidcTokenVerifierOptions,
)
from identity.ports.outbound.tenant_hierarchy_port import GlobalAuthzCatalogPort
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.config.settings import get_settings


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    db_provider: DatabaseProvider = request.app.state.db_provider
    async with db_provider.session() as session:
        yield session


def build_token_verifier(
    global_catalog: GlobalAuthzCatalogPort | None = None,
) -> TokenVerifierPort:
    """Build the generic multi-issuer OIDC JWKS token verifier (100% IdP-agnostic)."""
    settings = get_settings()

    jwks_url = settings.identity.jwks_url.strip()
    if not jwks_url and settings.idp_api_url:
        jwks_url = f"{settings.idp_api_url.rstrip('/')}/.well-known/jwks"

    jwks_host_header = settings.identity.jwks_host_header.strip() or None
    if jwks_host_header is None and settings.identity.issuer and settings.idp_api_url:
        issuer_netloc = urlparse(settings.identity.issuer).netloc
        api_netloc = urlparse(settings.idp_api_url).netloc
        if issuer_netloc and api_netloc and issuer_netloc != api_netloc:
            jwks_host_header = issuer_netloc

    accepted_audiences = settings.identity.accepted_audiences
    if not accepted_audiences and settings.control_plane_project_id:
        accepted_audiences = (settings.control_plane_project_id,)

    options = OidcTokenVerifierOptions(
        default_issuer=settings.identity.issuer,
        default_jwks_uri=jwks_url,
        default_audiences=tuple(accepted_audiences),
        default_jwks_host_header=jwks_host_header,
        allow_private_ips=settings.identity.allow_private_ips,
    )
    return OidcJwksTokenVerifierAdapter(options=options, global_catalog=global_catalog)


@lru_cache(maxsize=1)
def get_token_verifier() -> TokenVerifierPort:
    return build_token_verifier()
