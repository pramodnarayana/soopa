import asyncio
import ipaddress
import socket

from edi.application.use_cases.sftp_partners.create_sftp_partner_use_case import (
    CreateSFTPPartnerCmd,
    CreateSFTPPartnerUseCase,
)
from edi.application.use_cases.sftp_partners.delete_sftp_partner_use_case import (
    DeleteSFTPPartnerUseCase,
)
from edi.application.use_cases.sftp_partners.update_sftp_partner_use_case import (
    UpdateSFTPPartnerCmd,
    UpdateSFTPPartnerUseCase,
)
from edi.domain.exceptions import OrchestrationError, VaultError
from edi.ports.outbound.sftp_tester import SftpTesterPort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, HTTPException, status
from secret_store.ports.secret_store_port import SecretStorePort
from security.ports.cipher_port import CipherPort

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_field_encryption,
    get_secret_store,
    get_sftp_tester,
)
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    CreateSFTPPartnerRequest,
    PartnerResponse,
    TestConnectionResponse,
    TestSFTPConnectionRequest,
    TradingPartnerStatusResponse,
    UpdateSFTPPartnerRequest,
)
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error

router = APIRouter(tags=["Partners — SFTP"])


async def _get_client_key_from_vault(vault_ref: str, secret_store_port: SecretStorePort) -> str:
    vault_secret = await secret_store_port.retrieve_private_key(vault_ref)
    return vault_secret.decode("utf-8") if isinstance(vault_secret, bytes) else vault_secret


async def _is_ssrf_blocked(host: str) -> bool:
    """Return True if any resolved IP for `host` is a non-global address."""
    try:
        loop = asyncio.get_running_loop()
        addr_infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addr_infos:
            return True
        for info in addr_infos:
            sockaddr = info[4]
            resolved_ip = ipaddress.ip_address(sockaddr[0])
            if not resolved_ip.is_global:
                return True
        return False
    except (socket.gaierror, ValueError, OSError):
        return True


async def _validate_sftp_request(
    request: TestSFTPConnectionRequest, tenant_id: str
) -> TestConnectionResponse | None:
    if await _is_ssrf_blocked(request.host):
        return TestConnectionResponse(success=False, reason="SSRF blocked: Invalid target host")

    if request.credentials_vault_ref and not request.credentials_vault_ref.startswith(
        f"{tenant_id}/"
    ):
        return TestConnectionResponse(
            success=False, reason="Tenant isolation violation: Invalid vault reference"
        )
    return None


@router.post("/sftp/test", response_model=TestConnectionResponse, status_code=status.HTTP_200_OK)
async def test_sftp_connection(
    request: TestSFTPConnectionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: SecretStorePort = Depends(get_secret_store),
) -> TestConnectionResponse:
    """Tests an SFTP connection without saving a partner."""
    if not request.password and not request.credentials_vault_ref:
        return TestConnectionResponse(
            success=False, reason="Must provide either password or SSH key"
        )

    if validation_err := await _validate_sftp_request(request, tenant_id):
        return validation_err

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
    "/sftp/{partner_id}/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
)
@router.post(
    "/{partner_id}/sftp/test",
    response_model=TestConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def test_existing_sftp_connection(
    partner_id: str,
    request: TestSFTPConnectionRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    sftp_tester: SftpTesterPort = Depends(get_sftp_tester),
    vault_port: SecretStorePort = Depends(get_secret_store),
    field_encryption: CipherPort = Depends(get_field_encryption),
) -> TestConnectionResponse:
    """Tests an SFTP connection for an existing partner, pulling missing credentials from the DB."""

    if not request.password and not request.credentials_vault_ref:
        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
            if partner:
                if partner.password_encrypted:
                    try:
                        request.password = field_encryption.decrypt_str(partner.password_encrypted)
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

    if validation_err := await _validate_sftp_request(request, tenant_id):
        return validation_err

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
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    field_encryption: CipherPort = Depends(get_field_encryption),
) -> PartnerResponse:
    """Creates a new SFTP Partner directly in the Tenant Data Plane."""

    if not request.password and not request.credentials_vault_ref:
        raise HTTPException(
            status_code=400, detail="Must provide either password or credentials_vault_ref"
        )

    async with uow:
        service = CreateSFTPPartnerUseCase(uow=uow, field_encryption=field_encryption)

        cmd = CreateSFTPPartnerCmd(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            inbound_remote_path=request.inbound_remote_path,
            outbound_remote_path=request.outbound_remote_path,
            password=request.password,
            credentials_vault_ref=str(request.credentials_vault_ref)
            if request.credentials_vault_ref
            else None,
        )

        create_res = await service.create_sftp_partner(
            tenant_id, cmd, idempotency_key=idempotency_key
        )
        if create_res.is_err:
            raise_http_for_edi_error(create_res.unwrap_err())
        created = create_res.unwrap()
        await uow.commit()

        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, created.id)
            if not partner:
                raise HTTPException(status_code=404, detail="Partner not found after creation")

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            name=partner.name,
            type="SFTP",
            status=TradingPartnerStatusResponse.ACTIVE
            if partner.active
            else TradingPartnerStatusResponse.INACTIVE,
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
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
    field_encryption: CipherPort = Depends(get_field_encryption),
) -> PartnerResponse:
    """Updates an SFTP Partner in the Tenant Data Plane."""

    async with uow:
        service = UpdateSFTPPartnerUseCase(uow=uow, field_encryption=field_encryption)
        cmd = UpdateSFTPPartnerCmd(**request.model_dump(exclude_unset=True))
        upd_res = await service.update_sftp_partner(
            tenant_id, partner_id, cmd, idempotency_key=idempotency_key
        )
        if upd_res.is_err:
            raise_http_for_edi_error(upd_res.unwrap_err())
        await uow.commit()

        async with uow:
            partner = await uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
            if not partner:
                raise HTTPException(status_code=404, detail="Partner not found after update")

        return PartnerResponse(
            partner_id=partner.id,
            tenant_id=tenant_id,
            name=partner.name,
            type="SFTP",
            status=TradingPartnerStatusResponse.ACTIVE
            if partner.active
            else TradingPartnerStatusResponse.INACTIVE,
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
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> None:
    """Deletes an SFTP partner."""
    async with uow:
        try:
            use_case = DeleteSFTPPartnerUseCase(uow=uow)
            del_res = await use_case.delete_sftp_partner(
                tenant_id, partner_id, idempotency_key=idempotency_key
            )
            if del_res.is_err:
                raise_http_for_edi_error(del_res.unwrap_err())
            await uow.commit()
        except HTTPException:
            raise
        except OrchestrationError as e:
            raise OrchestrationError("Failed to update SFTP partner") from e
