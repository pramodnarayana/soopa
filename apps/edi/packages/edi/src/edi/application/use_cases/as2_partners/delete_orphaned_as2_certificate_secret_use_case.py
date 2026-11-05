"""Use case for deleting orphaned AS2 private keys discarded prior to partner persistence."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.domain.exceptions import Result

from edi.config.constants import SecretCategory
from edi.domain.exceptions import EdiError, EdiValidationError
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteOrphanedAS2CertificateSecretCmd:
    """Command DTO carrying the candidate secret store reference to delete."""

    vault_ref: str


class DeleteOrphanedAS2CertificateSecretUseCase:
    """Validates category namespace and active references before deleting an orphaned AS2 key."""

    def __init__(
        self,
        uow: ControlPlaneUnitOfWorkPort,
        secret_store: SecretStorePort,
    ) -> None:
        self._uow = uow
        self._secret_store = secret_store

    async def execute(
        self,
        cmd: DeleteOrphanedAS2CertificateSecretCmd,
    ) -> Result[bool, EdiError]:
        normalized_ref = self._secret_store.normalize_category_ref(
            cmd.vault_ref,
            SecretCategory.AS2_KEY.value,
        )
        if normalized_ref is None:
            logger.error(
                "delete_orphaned_as2_secret_invalid_category",
                requested_vault_ref=cmd.vault_ref,
            )
            return Result.fail(EdiValidationError.with_message("Invalid vault reference category."))

        in_use = await self._uow.as2_partners.is_vault_ref_in_use(normalized_ref)
        if in_use:
            logger.error(
                "delete_orphaned_as2_secret_rejected_in_use",
                vault_ref=normalized_ref,
            )
            return Result.fail(
                EdiValidationError.with_message(
                    "Cannot delete a private key that is currently in use."
                )
            )

        await self._secret_store.delete_secret(normalized_ref)
        logger.info("orphaned_as2_certificate_secret_deleted", vault_ref=normalized_ref)
        return Result.ok(True)
