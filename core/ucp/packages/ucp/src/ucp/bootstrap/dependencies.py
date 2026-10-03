from collections.abc import AsyncGenerator
from functools import lru_cache
from urllib.parse import urlparse

from database.provider import DatabaseProvider
from fastapi import Request
from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierPort,
    ZitadelTokenVerifierPortOptions,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.config.settings import get_settings


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    db_provider: DatabaseProvider = request.app.state.db_provider
    async with db_provider.session() as session:
        yield session


@lru_cache(maxsize=1)
def get_token_verifier() -> ZitadelTokenVerifierPort:
    settings = get_settings()

    # JWKS fetching uses the internal Cloud Map URL (no ALB hairpin) but overrides
    # the Host header to the public issuer domain. Zitadel is host-header sensitive:
    # it only serves /oauth/v2/keys when the Host header matches its configured
    # ZITADEL_EXTERNALDOMAIN. Sending the internal URL's hostname (e.g.
    # "zitadel.staging-cluster.local") would cause a 404 from Zitadel.
    jwks_url = (
        f"{settings.zitadel_api_url_value.rstrip('/')}/oauth/v2/keys"
        if settings.zitadel_api_url_value
        else None
    )
    # Extract the bare hostname from the public issuer URL (e.g. "identity.staging.flowwolf.io")
    # to use as the Host header when making internal JWKS requests.
    # urlparse is used (not str.split) so that issuer URLs with path components
    # (e.g. "https://host/path") are handled correctly.
    jwks_host_header = urlparse(settings.zitadel_issuer).netloc if settings.zitadel_issuer else None

    options = ZitadelTokenVerifierPortOptions(
        issuer=settings.zitadel_issuer,
        audience=[
            settings.zitadel_ucp_project_id,
            settings.identity.oauth_client_id,
        ],
        platform_org_id=settings.zitadel_platform_org_id,
        jwks_url=jwks_url,
        jwks_host_header=jwks_host_header,
    )
    return ZitadelTokenVerifierPort(options)
