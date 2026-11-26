"""Minimal 5-method provider-agnostic IdP Admin Port (Invariant 4 — Zero IdP Lock-In)."""

from __future__ import annotations

from typing import Protocol

from seedwork.domain.exceptions import Result

from identity.domain.dtos import EnterpriseSsoConfigDTO, ExternalIdentityRef, RealmRef
from identity.domain.exceptions import IdentityError


class IdentityProviderAdminPort(Protocol):
    """Thin provider-agnostic administrative contract implemented by Casdoor (or any OIDC IdP)."""

    async def create_user(
        self,
        *,
        realm: str,
        email: str,
        display_name: str,
        initial_password: str | None = None,
    ) -> Result[ExternalIdentityRef, IdentityError]: ...

    async def update_user(
        self,
        *,
        realm: str,
        external_subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> Result[None, IdentityError]: ...

    async def set_user_active(
        self,
        *,
        realm: str,
        external_subject: str,
        active: bool,
    ) -> Result[None, IdentityError]: ...

    async def delete_user(
        self,
        *,
        realm: str,
        external_subject: str,
    ) -> Result[None, IdentityError]: ...

    async def provision_dedicated_enterprise_realm(
        self,
        *,
        slug: str,
        display_name: str,
        sso_config: EnterpriseSsoConfigDTO | None = None,
    ) -> Result[RealmRef, IdentityError]: ...


__all__ = ["IdentityProviderAdminPort"]
