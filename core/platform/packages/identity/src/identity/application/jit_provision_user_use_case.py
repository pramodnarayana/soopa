"""Zero-Trust Just-In-Time (JIT) User Provisioning Use Case (B2C & Enterprise SSO)."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from identity.domain.dtos import ExternalIdentityDTO
from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.domain.user import User
from identity.ports.outbound.external_identity_repository_port import (
    ExternalIdentityRepositoryPort,
)
from identity.ports.outbound.tenant_hierarchy_port import GlobalAuthzCatalogPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class JitProvisionUserCommand:
    """Command to resolve or zero-trust JIT-provision a canonical platform user from OIDC claims."""

    idp_issuer: str
    idp_subject: str
    email: str | None
    email_verified: bool
    display_name: str
    idp_realm_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class JitProvisionUserResult:
    user_id: str
    external_identity: ExternalIdentityDTO
    created: bool


class JitProvisionUserUseCase:
    """Resolves `(idp_issuer, idp_subject)` -> `iam_usr_...` with anti-pre-hijacking guards.

    Security invariants:
      1. `idp_issuer` MUST be registered and active in `GlobalAuthzCatalogPort.get_trusted_issuer`.
      2. Never auto-merges an unlinked `(idp_issuer, idp_subject)` into an existing email unless
         BOTH `email_verified == True` AND `idp_issuer` is an authorized Enterprise SSO issuer
         for that verified email domain (`email_domain_routes`).
    """

    def __init__(
        self,
        *,
        external_identity_repo: ExternalIdentityRepositoryPort,
        user_repo: UserRepositoryPort,
        global_catalog: GlobalAuthzCatalogPort,
    ) -> None:
        self._external_identities = external_identity_repo
        self._users = user_repo
        self._catalog = global_catalog

    async def execute(
        self, command: JitProvisionUserCommand
    ) -> Result[JitProvisionUserResult, IdentityError]:
        normalized_issuer = command.idp_issuer.rstrip("/")
        trusted = self._catalog.get_trusted_issuer(normalized_issuer)
        if trusted is None or not trusted.is_active:
            logger.error(
                "jit_provision.untrusted_issuer",
                idp_issuer=normalized_issuer,
                idp_subject=command.idp_subject,
            )
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.UNTRUSTED_ISSUER,
                    message=f"OIDC issuer '{normalized_issuer}' is not trusted.",
                    details={"idp_issuer": normalized_issuer},
                )
            )

        existing_link = await self._external_identities.find_by_issuer_subject(
            idp_issuer=normalized_issuer,
            idp_subject=command.idp_subject,
        )
        if existing_link is not None:
            return Result.ok(
                JitProvisionUserResult(
                    user_id=existing_link.user_id,
                    external_identity=existing_link,
                    created=False,
                )
            )

        cleaned_email = (command.email or "").strip().lower()
        if not cleaned_email or "@" not in cleaned_email:
            logger.error(
                "jit_provision.missing_email",
                idp_issuer=normalized_issuer,
                idp_subject=command.idp_subject,
            )
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.VALIDATION_FAILED,
                    message="Valid email claim is required for JIT user provisioning.",
                )
            )

        existing_user = await self._users.find_by_email(cleaned_email)
        if existing_user is not None:
            if not self._is_authorized_enterprise_auto_link(
                email=cleaned_email,
                email_verified=command.email_verified,
                idp_issuer=normalized_issuer,
                idp_realm_name=command.idp_realm_name,
            ):
                logger.error(
                    "jit_provision.account_link_confirmation_required",
                    idp_issuer=normalized_issuer,
                    idp_subject=command.idp_subject,
                    email_verified=command.email_verified,
                )
                return Result.fail(
                    IdentityError(
                        code=IdentityErrorCode.ACCOUNT_LINK_CONFIRMATION_REQUIRED,
                        message=(
                            "An account with this email already exists. Explicit authenticated "
                            "account linking is required."
                        ),
                    )
                )

            link = await self._external_identities.link_identity(
                user_id=existing_user.id,
                idp_issuer=normalized_issuer,
                idp_subject=command.idp_subject,
                idp_realm_name=command.idp_realm_name,
            )
            logger.info(
                "jit_provision.enterprise_identity_linked",
                user_id=existing_user.id,
                idp_issuer=normalized_issuer,
            )
            return Result.ok(
                JitProvisionUserResult(
                    user_id=existing_user.id,
                    external_identity=link,
                    created=False,
                )
            )

        user_res = User.create(
            idp_user_id=command.idp_subject,
            email=cleaned_email,
            name=command.display_name.strip() or cleaned_email.split("@", maxsplit=1)[0],
        )
        if user_res.is_err:
            return Result.fail(user_res.unwrap_err())

        new_user = user_res.unwrap()
        await self._users.save(new_user)
        link = await self._external_identities.link_identity(
            user_id=new_user.id,
            idp_issuer=normalized_issuer,
            idp_subject=command.idp_subject,
            idp_realm_name=command.idp_realm_name,
        )
        logger.info(
            "jit_provision.user_created",
            user_id=new_user.id,
            idp_issuer=normalized_issuer,
            idp_realm=command.idp_realm_name,
        )
        return Result.ok(
            JitProvisionUserResult(
                user_id=new_user.id,
                external_identity=link,
                created=True,
            )
        )

    def _is_authorized_enterprise_auto_link(
        self,
        *,
        email: str,
        email_verified: bool,
        idp_issuer: str,
        idp_realm_name: str | None,
    ) -> bool:
        if not email_verified:
            return False
        domain = email.rsplit("@", maxsplit=1)[1].lower()
        route = self._catalog.get_email_domain_route(domain)
        if route is None or route.verified_at is None:
            return False
        issuer_ok = route.idp_issuer.rstrip("/") == idp_issuer.rstrip("/")
        realm_ok = not route.idp_realm_name or route.idp_realm_name == idp_realm_name
        return issuer_ok and realm_ok


__all__ = ["JitProvisionUserCommand", "JitProvisionUserResult", "JitProvisionUserUseCase"]
