from __future__ import annotations

from dataclasses import dataclass

import structlog
from identity.domain.api_token import ApiToken
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.application.use_cases.api_key_authenticator import invalidate_api_key_cache
from ucp.domain.exceptions import TokenNotFoundUcpError, UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateApiTokenCommand:
    name: str | None = None
    active: bool | None = None


class UpdateApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, token_id: str, tenant_id: str, command: UpdateApiTokenCommand
    ) -> Result[ApiToken, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, token_id=token_id)
        bound_logger.info("api_token_update.started")

        async with self.uow:
            token = await self.uow.api_token_repo.get_by_id(token_id, tenant_id)
            if token is None:
                bound_logger.error("api_token_update.not_found")
                return Result.fail(TokenNotFoundUcpError.for_id(token_id))

            if command.name is not None:
                rename_res = token.rename(command.name)
                if rename_res.is_err:
                    err = rename_res.unwrap_err()
                    bound_logger.error(
                        "api_token_update.rename_failed",
                        code=err.code.value,
                        reason=err.message,
                    )
                    return Result.fail(translate_identity_error(err))

            if command.active is not None:
                if command.active:
                    act_res = token.activate()
                    if act_res.is_err:
                        err = act_res.unwrap_err()
                        bound_logger.error(
                            "api_token_update.activate_failed",
                            code=err.code.value,
                            reason=err.message,
                        )
                        return Result.fail(translate_identity_error(err))
                elif token.active:
                    rev_res = token.revoke()
                    if rev_res.is_err:
                        err = rev_res.unwrap_err()
                        bound_logger.error(
                            "api_token_update.revoke_failed",
                            code=err.code.value,
                            reason=err.message,
                        )
                        return Result.fail(translate_identity_error(err))

            saved = await self.uow.api_token_repo.save(token)
            await self.uow.commit()

        if not saved.active:
            invalidate_api_key_cache(saved.client_id)

        bound_logger.info("api_token_update.completed", active=saved.active)
        return Result.ok(saved)
