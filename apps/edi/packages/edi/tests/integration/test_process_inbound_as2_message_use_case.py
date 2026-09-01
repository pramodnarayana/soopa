from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from edi.application.dto import ProcessInboundAs2Command
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)


@pytest.fixture
def mock_uow():
    return AsyncMock()


@pytest.fixture
def mock_vault():
    return AsyncMock()


@pytest.fixture
def mock_dp_factory():
    return MagicMock()


@pytest.fixture
def mock_crypto_service():
    """
    Fake CryptoServicePort — returns predictable values so the application
    logic (not the crypto library) is what's exercised.
    """
    svc = MagicMock()
    svc.decrypt.return_value = b"decrypted"
    svc.verify_signature.return_value = (True, b"verified payload")
    svc.sign.return_value = b"signed_mdn"
    return svc


@pytest.fixture
def service(mock_uow, mock_vault, mock_dp_factory, mock_crypto_service):
    return ProcessInboundAs2MessageUseCase(
        control_plane_uow=mock_uow,
        dp_factory=mock_dp_factory,
        secret_store=mock_vault,
        crypto_service=mock_crypto_service,
    )


@pytest.mark.asyncio
async def test_process_inbound_message_bad_request(service):
    headers = {"AS2-From": "me", "AS2-To": "you"}
    body_bytes = b"bad body"

    with patch(
        "edi.application.use_cases.process_inbound_as2_message_use_case.parse_as2_request"
    ) as mock_parse:
        mock_parse.side_effect = ValueError("Missing headers")

        with pytest.raises(ValueError, match="Bad Request: Missing headers"):
            await service.process_inbound_message(
                ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
            )


@pytest.mark.asyncio
async def test_process_inbound_message_partnership_not_found(service):
    headers = {"AS2-From": "unknown", "AS2-To": "unknown2"}
    body_bytes = b"valid body"

    with patch(
        "edi.application.use_cases.process_inbound_as2_message_use_case.parse_as2_request"
    ) as mock_parse:
        mock_msg = MagicMock()
        mock_msg.as2_from = "unknown"
        mock_msg.as2_to = "unknown2"
        mock_parse.return_value = mock_msg

        service.control_plane_uow.as2_partnerships.get_partnership_by_as2_ids.return_value = None

        with pytest.raises(ValueError, match="Partnership not configured"):
            await service.process_inbound_message(
                ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
            )


@pytest.mark.asyncio
async def test_process_inbound_message_success(service):
    headers = {"AS2-From": "p1", "AS2-To": "p2", "Message-ID": "123"}
    body_bytes = b"valid body"

    with patch(
        "edi.application.use_cases.process_inbound_as2_message_use_case.parse_as2_request"
    ) as mock_parse:
        mock_msg = MagicMock()
        mock_msg.as2_from = "p1"
        mock_msg.as2_to = "p2"
        mock_msg.message_id = "123"
        mock_parse.return_value = mock_msg

        mock_partnership = MagicMock()
        mock_local_partner = MagicMock()
        mock_remote_partner = MagicMock()

        service.control_plane_uow.as2_partnerships.get_partnership_by_as2_ids.return_value = (
            mock_partnership,
            mock_local_partner,
            mock_remote_partner,
        )

        with (
            patch.object(service, "_retrieve_keys") as mock_keys,
            patch.object(service, "_unbox_payload") as mock_unbox,
            patch.object(service, "_extract_pure_edi") as mock_extract,
            patch.object(service, "_save_transaction") as mock_save,
        ):
            mock_keys.return_value = (None, None, None)
            mock_unbox.return_value = (b"unboxed_payload", "mic123")
            mock_extract.return_value = b"ISA*EDI"

            body, _mdn_headers = await service.process_inbound_message(
                ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
            )

            assert "mic123" in body.decode()
            mock_save.assert_awaited_once_with(
                partnership=mock_partnership, as2_msg=mock_msg, pure_edi_bytes=b"ISA*EDI"
            )


@pytest.mark.asyncio
async def test_private_methods_coverage(service):
    # Test _retrieve_keys
    local_partner = MagicMock(private_key_vault_ref="loc_priv", public_cert_vault_ref="loc_pub")
    remote_partner = MagicMock(public_cert_vault_ref="rem_pub")
    service.secret_store.retrieve_secret.return_value = b"secret_val"

    local_priv, local_cert, remote_cert = await service._retrieve_keys(
        local_partner, remote_partner
    )
    assert local_priv == b"secret_val"
    assert local_cert == b"secret_val"
    assert remote_cert == b"secret_val"

    # Test _extract_pure_edi
    edi = service._extract_pure_edi(b"Content-Type: text/plain\r\n\r\nISA*EDI")
    assert edi == b"ISA*EDI"

    # Test _reconstruct_smime_headers
    headers = {"content-type": "application/pkcs7-mime", "content-disposition": "attachment"}
    smime_hdr = service._reconstruct_smime_headers(headers)
    assert b"Content-Type: application/pkcs7-mime" in smime_hdr
    assert b"Content-Transfer-Encoding: binary" in smime_hdr

    # Test _save_transaction (failure path: no tenant found)
    service.control_plane_uow.inbound_routes.get_tenant_by_isa.return_value = None
    with pytest.raises(ValueError, match="No tenant could be identified for this ISA pair"):
        await service._save_transaction(
            MagicMock(tenant_id=None),
            MagicMock(),
            b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~",
        )


@pytest.mark.asyncio
async def test_crypto_pipeline_coverage(service):
    """
    Tests the crypto orchestration logic in As2ReceiverService.
    Crypto operations are delegated to self.crypto_service (CryptoServicePort),
    so we assert the service calls the port correctly — not the smime library.
    """
    # Test _verify_and_calculate_mic (no multipart boundary)
    service.crypto_service.verify_signature.return_value = (True, b"verified payload")
    mic, verified = service._verify_and_calculate_mic(
        b"Content-Type: text/plain\r\n\r\nunsigned payload", b"remote_cert", "msg-1"
    )
    assert mic is not None
    assert verified == b"verified payload"

    # Test _verify_and_calculate_mic with multipart boundary
    verify_entity = (
        b"Content-Type: multipart/signed; boundary=abc\r\n\r\n--abc\r\nsome content\r\n--abc--"
    )
    mic, payload = service._verify_and_calculate_mic(verify_entity, b"rem_cert", "msg-1")
    assert payload == b"verified payload"

    # Test _decrypt_entity (initial attempt succeeds)
    service.crypto_service.decrypt.return_value = b"decrypted"
    res = service._decrypt_entity(b"content", {"content-type": "app/pkcs7"}, b"priv", b"cert")
    assert res == b"decrypted"

    # Test _decrypt_entity (initial fails, fallback succeeds via header reconstruction)
    service.crypto_service.decrypt.side_effect = [Exception("fail"), b"decrypted_fallback"]
    res = service._decrypt_entity(b"content", {"content-type": "app/pkcs7"}, b"priv", b"cert")
    assert res == b"decrypted_fallback"
    service.crypto_service.decrypt.side_effect = None  # Reset

    # Test _decrypt_entity (both fail → ValueError)
    service.crypto_service.decrypt.side_effect = [Exception("fail1"), Exception("fail2")]
    with pytest.raises(ValueError, match="Decryption failed"):
        service._decrypt_entity(b"content", {"content-type": "app/pkcs7"}, b"priv", b"cert")
    service.crypto_service.decrypt.side_effect = None  # Reset

    # Test _unbox_payload (encrypted, becomes signed after decryption)
    with (
        patch.object(service, "_decrypt_entity") as mock_decrypt,
        patch.object(service, "_verify_and_calculate_mic") as mock_verify,
    ):
        mock_decrypt.return_value = (
            b"Content-Type: application/pkcs7-signature\r\n\r\nsigned payload"
        )
        mock_verify.return_value = ("mic123", b"verified")

        as2_msg = MagicMock(
            payload=b"encrypted", is_encrypted=True, is_signed=False, message_id="123"
        )
        payload, mic = service._unbox_payload(as2_msg, {}, b"priv", b"loc_cert", b"rem_cert")

        assert mic == "mic123"
        assert payload == b"verified"
        mock_decrypt.assert_called_once()
        mock_verify.assert_called_once()

    # Test _unbox_payload (plain unsigned/unencrypted — MIC calculated directly)
    as2_msg_plain = MagicMock(
        payload=b"plain", is_encrypted=False, is_signed=False, message_id="123"
    )
    payload, mic = service._unbox_payload(as2_msg_plain, {}, None, None, None)
    assert payload == b"plain"
    assert mic is not None


@pytest.mark.asyncio
async def test_save_transaction_success(service):
    service.control_plane_uow.inbound_routes.get_tenant_by_isa.return_value = "1"

    mock_dp_uow = AsyncMock()
    mock_dp_uow.transactions.create_edi_message.return_value = "msg-1"

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_dp_uow
    service.dp_factory.get_data_plane_uow.return_value = mock_ctx

    mock_partnership = MagicMock(
        tenant_id=1,
        mdn_type="SYNC",
        signature_algorithm="SHA256",
        encryption_algorithm="AES256",
    )
    mock_as2_msg = MagicMock(as2_from="ME", as2_to="YOU", message_id="msg-1")
    _events = []
    mock_as2_msg.add_domain_event.side_effect = lambda e: _events.append(e)
    mock_as2_msg.collect_events.side_effect = lambda: _events.copy()

    res = await service._save_transaction(
        mock_partnership,
        mock_as2_msg,
        b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~",
    )

    assert res == "msg-1"
    mock_dp_uow.transactions.create_edi_message.assert_awaited_once()
    # The use case now adds domain events to the aggregate and delegates persistence
    # via transactions.save(aggregate). publish_outbox_event is NOT called directly.
    mock_dp_uow.transactions.save.assert_awaited_once()
    saved_aggregate = mock_dp_uow.transactions.save.call_args[0][0]
    from edi.domain.events import TransformRequestedEvent

    domain_events = saved_aggregate.domain_events
    assert len(domain_events) == 1
    assert isinstance(domain_events[0], TransformRequestedEvent)
    assert domain_events[0].explicit_idempotency_key == "msg-1"
    mock_dp_uow.commit.assert_awaited_once()
