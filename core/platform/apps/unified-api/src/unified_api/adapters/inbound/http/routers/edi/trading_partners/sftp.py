from typing import Any

from database.exceptions import DuplicateEntityError
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork,
)
from edi.application.dto import (
    UNSET,
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from edi.application.use_cases import SFTPPartnerService
from edi.domain.exceptions import OrchestrationError, VaultError
from edi.ports.outbound.secret_store import SecretStorePort
from edi.ports.outbound.sftp_tester import SftpTesterPort
from fastapi import APIRouter, Depends, HTTPException, status

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_secret_store,
    get_sftp_tester,
)
from unified_api.adapters.inbound.http.dtos.edi.dtos import (
    CreateSFTPPartnerRequest,
    PartnerResponse,
    TestConnectionResponse,
    TestSFTPConnectionRequest,
    UpdateSFTPPartnerRequest,
)

router = APIRouter(tags=["Partners — SFTP"])


async def _get_client_key_from_vault(vault_ref: str, secret_store_port: SecretStorePort) -> str:
    vault_secret = await secret_store_port.retrieve_private_key(vault_ref)
    return vault_secret.decode("utf-8") if isinstance(vault_secret, bytes) else vault_secret


@router.post("/sftp/test", response_model=TestConnectionResponse, status_code=status.HTTP_200_OK)
async def test_sftp_connection(
    request: TestSFTPConnectionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: SecretStorePort = Depends(get_secret_store),
) -> Any:
    """Tests an SFTP connection without saving a partner."""
    if not request.password and not request.credentials_vault_ref:
        return TestConnectionResponse(
            success=False, reason="Must provide either password or SSH key"
        )

    client_key_string = None
    if request.credentials_vault_ref:
        try:
            client_key_string = await _get_client_key_from_vault(
                request.credentials_vault_ref, vault_port
            )
        except (ValueError, VaultError) as e:
            return TestConnectionResponse(success=False, reason=f"Failed to fetch SSH key: {e}")

    success, reason = await sftp_tester.test_connection(
        host=request.host,
        port=request.port,
        username=request.username,
        client_key_string=client_key_string,
    )
    return TestConnectionResponse(success=success, reason=reason)


@router.post(
    "/{partner_id}/sftp/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def test_existing_sftp_connection(
    partner_id: str,
    request: TestSFTPConnectionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: SecretStorePort = Depends(get_secret_store),
) -> Any:
    """Tests an SFTP connection for an existing partner, pulling missing credentials from the DB."""
    from edi.adapters.outbound.database.encryption import db_encryption

    if not request.password and not request.credentials_vault_ref:
        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
            if partner:
                if partner.password_encrypted:
                    try:
                        request.password = db_encryption.decrypt(partner.password_encrypted)
                    except (ValueError, VaultError) as e:
                        return TestConnectionResponse(
                            success=False,
                            reason=f"Failed to decrypt stored password: {e}",
                        )
                elif partner.credentials_vault_ref:
                    request.credentials_vault_ref = partner.credentials_vault_ref

    if not request.password and not request.credentials_vault_ref:
        return TestConnectionResponse(
            success=False, reason="Must provide either password or SSH key"
        )

    client_key_string = None
    if request.credentials_vault_ref:
        try:
            client_key_string = await _get_client_key_from_vault(
                request.credentials_vault_ref, vault_port
            )
        except (ValueError, VaultError) as e:
            return TestConnectionResponse(success=False, reason=f"Failed to fetch SSH key: {e}")

    success, reason = await sftp_tester.test_connection(
        host=request.host,
        port=request.port,
        username=request.username,
        client_key_string=client_key_string,
    )
    return TestConnectionResponse(success=success, reason=reason)


@router.post("/sftp", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_sftp_partner(
    request: CreateSFTPPartnerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """Creates a new SFTP Partner directly in the Tenant Data Plane."""
    from database.exceptions import DuplicateEntityError

    if not request.password and not request.credentials_vault_ref:
        raise HTTPException(
            status_code=400, detail="Must provide either password or credentials_vault_ref"
        )

    async with uow:
        service = SFTPPartnerService(uow=uow)

        cmd = CreateSFTPPartnerCmd(
            name=request.name if request.name is not None else UNSET,
            host=request.host,
            port=request.port,
            username=request.username,
            inbound_remote_path=request.inbound_remote_path,
            outbound_remote_path=request.outbound_remote_path,
            credentials_vault_ref=str(request.credentials_vault_ref)
            if request.credentials_vault_ref
            else "",
        )

        try:
            _ = await service.create_sftp_partner(tenant_id, cmd, idempotency_key=idempotency_key)
            await uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except DuplicateEntityError as e:
            raise HTTPException(status_code=400, detail="Database integrity error.") from e

        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, _.id)
            if not partner:
                raise HTTPException(status_code=404, detail="Partner not found after creation")

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            name=partner.name,
            type="SFTP",
            status="ACTIVE" if partner.active else "INACTIVE",
            active=partner.active,
            host=partner.host,
            port=partner.port,
            username=partner.username,
            inbound_remote_path=partner.inbound_remote_path,
            outbound_remote_path=partner.outbound_remote_path,
            host_key=partner.host_key,
        )


@router.put("/sftp/{partner_id}", response_model=PartnerResponse)
async def update_sftp_partner(
    partner_id: str,
    request: UpdateSFTPPartnerRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """Updates an SFTP Partner in the Tenant Data Plane."""
    async with uow:
        service = SFTPPartnerService(uow=uow)
        cmd = UpdateSFTPPartnerCmd(**request.model_dump(exclude_unset=True))
        try:
            _ = await service.update_sftp_partner(
                tenant_id, partner_id, cmd, idempotency_key=idempotency_key
            )
            await uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except DuplicateEntityError as e:
            raise HTTPException(status_code=400, detail="Database integrity error.") from e

        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
            if not partner:
                raise HTTPException(status_code=404, detail="Partner not found after update")

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            name=partner.name,
            type="SFTP",
            status="ACTIVE" if partner.active else "INACTIVE",
            active=partner.active,
            host=partner.host,
            port=partner.port,
            username=partner.username,
            inbound_remote_path=partner.inbound_remote_path,
            outbound_remote_path=partner.outbound_remote_path,
            host_key=partner.host_key,
        )


@router.delete("/sftp/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sftp_partner(
    partner_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    """Deletes an SFTP partner."""
    async with uow:
        try:
            service = SFTPPartnerService(uow=uow)
            await service.delete_sftp_partner(
                tenant_id, partner_id, idempotency_key=idempotency_key
            )
            await uow.commit()
        except DuplicateEntityError as e:
            raise HTTPException(
                status_code=400, detail="Partner is in use and cannot be deleted."
            ) from e
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except OrchestrationError as e:
            raise OrchestrationError("Failed to update SFTP partner") from e
