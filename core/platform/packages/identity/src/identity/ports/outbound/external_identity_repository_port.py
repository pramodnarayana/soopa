"""Outbound repository port for composite `(idp_issuer, idp_subject) -> user_id` links."""

from __future__ import annotations

from typing import Protocol

from identity.domain.dtos import ExternalIdentityDTO


class ExternalIdentityRepositoryPort(Protocol):
    """Persists and resolves IdP-agnostic external identity bindings."""

    async def find_by_issuer_subject(
        self,
        *,
        idp_issuer: str,
        idp_subject: str,
    ) -> ExternalIdentityDTO | None: ...

    async def list_for_user(self, *, user_id: str) -> tuple[ExternalIdentityDTO, ...]: ...

    async def link_identity(
        self,
        *,
        user_id: str,
        idp_issuer: str,
        idp_subject: str,
        idp_realm_name: str | None = None,
    ) -> ExternalIdentityDTO: ...


__all__ = ["ExternalIdentityRepositoryPort"]
