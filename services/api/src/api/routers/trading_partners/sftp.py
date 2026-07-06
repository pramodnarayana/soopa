from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id
from sqlalchemy.exc import IntegrityError

from api.adapters.http.dtos import (
    CreateSFTPPartnerRequest,
    PartnerResponse,
    TestConnectionResponse,
    TestSFTPConnectionRequest,
    UpdateSFTPPartnerRequest,
)
from api.core.provisioning import ProvisioningService
from api.core.uow import UnitOfWork
from api.dependencies import (
    get_sftp_tester,
    get_tenant_uow,
    get_vault,
)
from api.domain.models import (
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from api.ports.sftp_tester import SftpTesterPort
from api.ports.vault import VaultPort

router = APIRouter(tags=["Partners — SFTP"])


async def _get_client_key_from_vault(vault_ref: str, vault_port: VaultPort) -> str:
    vault_secret = vault_port.retrieve_private_key(vault_ref)
    return vault_secret.decode("utf-8") if isinstance(vault_secret, bytes) else vault_secret


@router.post("/sftp/test", response_model=TestConnectionResponse, status_code=status.HTTP_200_OK)
async def test_sftp_connection(
    request: TestSFTPConnectionRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: VaultPort = Depends(get_vault),
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
        except Exception as e:
            return TestConnectionResponse(success=False, reason=f"Failed to fetch SSH key: {e}")

    success, reason = await sftp_tester.test_connection(
        host=request.host,
        port=request.port,
        username=request.username,
        password=request.password,
        client_key_string=client_key_string,
    )
    return TestConnectionResponse(success=success, reason=reason)


@router.post(
    "/{partner_id}/sftp/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def test_existing_sftp_connection(
    partner_id: UUID,
    request: TestSFTPConnectionRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: VaultPort = Depends(get_vault),
) -> Any:
    """Tests an SFTP connection for an existing partner, pulling missing credentials from the DB."""
    from database.encryption import db_encryption

    if not request.password and not request.credentials_vault_ref:
        async with uow:
            if uow.control_plane:
                partner = await uow.control_plane.get_sftp_partner(tenant_id, partner_id)
                if partner:
                    if partner.password_encrypted:
                        try:
                            request.password = db_encryption.decrypt(partner.password_encrypted)
                        except Exception as e:
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
        except Exception as e:
            return TestConnectionResponse(success=False, reason=f"Failed to fetch SSH key: {e}")

    success, reason = await sftp_tester.test_connection(
        host=request.host,
        port=request.port,
        username=request.username,
        password=request.password,
        client_key_string=client_key_string,
    )
    return TestConnectionResponse(success=success, reason=reason)


@router.post("/sftp", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_sftp_partner(
    request: CreateSFTPPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Creates a new SFTP Partner directly in the Tenant Data Plane."""
    from sqlalchemy.exc import IntegrityError

    if not request.password and not request.credentials_vault_ref:
        raise HTTPException(
            status_code=400, detail="Must provide either password or credentials_vault_ref"
        )

    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)

        cmd = CreateSFTPPartnerCmd(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            inbound_remote_path=request.inbound_remote_path,
            outbound_remote_path=request.outbound_remote_path,
            password=request.password,
            credentials_vault_ref=request.credentials_vault_ref,
            host_key=request.host_key,
        )

        try:
            _ = await service.create_sftp_partner(tenant_id, cmd)
            await uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except IntegrityError as e:
            raise HTTPException(status_code=400, detail="Database integrity error.") from e

        async with uow:
            if not uow.control_plane:
                raise HTTPException(status_code=500, detail="Data plane not initialized")
            partner = await uow.control_plane.get_sftp_partner(tenant_id, _.partner_id)
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
    partner_id: UUID,
    request: UpdateSFTPPartnerRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """Updates an SFTP Partner in the Tenant Data Plane."""
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)
        cmd = UpdateSFTPPartnerCmd(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            inbound_remote_path=request.inbound_remote_path,
            outbound_remote_path=request.outbound_remote_path,
            password=request.password,
            credentials_vault_ref=request.credentials_vault_ref,
            host_key=request.host_key,
            active=request.active,
        )
        try:
            _ = await service.update_sftp_partner(tenant_id, partner_id, cmd)
            await uow.commit()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except IntegrityError as e:
            raise HTTPException(status_code=400, detail="Database integrity error.") from e

        async with uow:
            if not uow.control_plane:
                raise HTTPException(status_code=500, detail="Data plane not initialized")
            partner = await uow.control_plane.get_sftp_partner(tenant_id, partner_id)
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
    partner_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    """Deletes an SFTP partner."""
    async with uow:
        try:
            if uow.control_plane is None:
                raise HTTPException(status_code=500, detail="Tenant data plane not available")
            await uow.control_plane.delete_sftp_partner(tenant_id, partner_id)
            await uow.commit()
        except IntegrityError as e:
            raise HTTPException(
                status_code=400, detail="Partner is in use and cannot be deleted."
            ) from e
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
