from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.services.as2_receiver_service import As2ReceiverService


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_vault():
    return MagicMock()


@pytest.fixture
def mock_db_router():
    return MagicMock()


@pytest.fixture
def service(mock_session, mock_vault, mock_db_router):
    svc = As2ReceiverService(mock_session, mock_vault, mock_db_router)
    svc.uow = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_process_inbound_message_bad_request(service):
    # Test step 1 failure: Bad Request parsing
    headers = {"AS2-From": "me", "AS2-To": "you"}
    body_bytes = b"bad body"

    with patch("api.services.as2_receiver_service.parse_as2_request") as mock_parse:
        mock_parse.side_effect = ValueError("Missing headers")

        with pytest.raises(ValueError, match="Bad Request: Missing headers"):
            await service.process_inbound_message(headers, body_bytes)


@pytest.mark.asyncio
async def test_process_inbound_message_partnership_not_found(service):
    # Test step 2 failure: Partnership lookup fails
    headers = {"AS2-From": "unknown", "AS2-To": "unknown2"}
    body_bytes = b"valid body"

    with patch("api.services.as2_receiver_service.parse_as2_request") as mock_parse:
        mock_msg = MagicMock()
        mock_msg.as2_from = "unknown"
        mock_msg.as2_to = "unknown2"
        mock_parse.return_value = mock_msg

        service.uow.as2_partnerships.get_partnership_by_as2_ids.return_value = None

        with pytest.raises(ValueError, match="Partnership not configured"):
            await service.process_inbound_message(headers, body_bytes)


@pytest.mark.asyncio
async def test_process_inbound_message_success(service):
    headers = {"AS2-From": "p1", "AS2-To": "p2", "Message-ID": "123"}
    body_bytes = b"valid body"

    with patch("api.services.as2_receiver_service.parse_as2_request") as mock_parse:
        mock_msg = MagicMock()
        mock_msg.as2_from = "p1"
        mock_msg.as2_to = "p2"
        mock_msg.message_id = "123"
        mock_parse.return_value = mock_msg

        mock_partnership = MagicMock()
        mock_local_partner = MagicMock()
        mock_remote_partner = MagicMock()

        service.uow.as2_partnerships.get_partnership_by_as2_ids.return_value = (
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

            body, mdn_headers = await service.process_inbound_message(headers, body_bytes)

            assert "mic123" in body.decode()
            mock_save.assert_awaited_once_with(
                partnership=mock_partnership, as2_msg=mock_msg, pure_edi_bytes=b"ISA*EDI"
            )


@pytest.mark.asyncio
async def test_private_methods_coverage(service):
    # Test _retrieve_keys
    local_partner = MagicMock(private_key_vault_ref="loc_priv", public_cert_vault_ref="loc_pub")
    remote_partner = MagicMock(public_cert_vault_ref="rem_pub")
    service.vault.retrieve_secret.return_value = b"secret_val"

    local_priv, local_cert, remote_cert = service._retrieve_keys(local_partner, remote_partner)
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

    # Test _save_transaction (failure path)
    service.global_session.execute = AsyncMock(
        return_value=MagicMock(first=MagicMock(return_value=None))
    )
    with pytest.raises(ValueError, match="Tenant routing failed"):
        await service._save_transaction(
            MagicMock(tenant_id=1),
            MagicMock(),
            b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~",
        )


@pytest.mark.asyncio
async def test_crypto_pipeline_coverage(service):
    # Mock verify_signature for the whole test since it is an external dependency we shouldn't test deeply here
    with patch("api.services.as2_receiver_service.verify_signature") as mock_verify:
        mock_verify.return_value = (True, b"verified payload")

        # Test _verify_and_calculate_mic (unsigned payload)
        mic, verified = service._verify_and_calculate_mic(
            b"Content-Type: text/plain\r\n\r\nunsigned payload", b"remote_cert", "msg-1"
        )
        assert mic is not None
        assert verified == b"verified payload"

        # Test _verify_and_calculate_mic with mock boundary
        verify_entity = (
            b"Content-Type: multipart/signed; boundary=abc\r\n\r\n--abc\r\nsome content\r\n--abc--"
        )
        mic, payload = service._verify_and_calculate_mic(verify_entity, b"rem_cert", "msg-1")
        assert payload == b"verified payload"

    # Test _decrypt_entity (fallback)
    with patch("api.services.as2_receiver_service.decrypt_payload") as mock_decrypt:
        # First call fails, second call (fallback) succeeds
        mock_decrypt.side_effect = [Exception("fail"), b"decrypted"]
        res = service._decrypt_entity(b"content", {"content-type": "app/pkcs7"}, b"priv", b"cert")
        assert res == b"decrypted"

        # Both fail
        mock_decrypt.side_effect = [Exception("fail1"), Exception("fail2")]
        with pytest.raises(ValueError, match="Decryption failed"):
            service._decrypt_entity(b"content", {"content-type": "app/pkcs7"}, b"priv", b"cert")

    # Test _unbox_payload
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

        # Unbox an encrypted but not initially signed message (it becomes signed after decryption)
        payload, mic = service._unbox_payload(as2_msg, {}, b"priv", b"loc_cert", b"rem_cert")

        assert mic == "mic123"
        assert payload == b"verified"
        mock_decrypt.assert_called_once()
        mock_verify.assert_called_once()

    # Test _unbox_payload (unsigned, unencrypted)
    as2_msg_plain = MagicMock(
        payload=b"plain", is_encrypted=False, is_signed=False, message_id="123"
    )
    payload, mic = service._unbox_payload(as2_msg_plain, {}, None, None, None)
    assert payload == b"plain"
    assert mic is not None


@pytest.mark.asyncio
async def test_save_transaction_success(service):
    # Test _save_transaction success path
    mock_tenant = MagicMock(id=1)
    mock_shard = MagicMock(dsn="sqlite:///:memory:")
    mock_shard.name = "shard1"

    mock_result = MagicMock()
    mock_result.first.return_value = (mock_tenant, mock_shard)
    service.global_session.execute = AsyncMock(return_value=mock_result)

    mock_session = AsyncMock()

    async def mock_async_gen():
        yield mock_session

    service.db_router.get_tenant_session = MagicMock(return_value=mock_async_gen())

    with patch(
        "api.adapters.transaction_repository.SqlAlchemyTransactionRepository"
    ) as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.create_edi_message.return_value = "msg-1"
        mock_repo_cls.return_value = mock_repo

        mock_partnership = MagicMock(
            tenant_id=1,
            mdn_type="SYNC",
            signature_algorithm="SHA256",
            encryption_algorithm="AES256",
        )
        mock_as2_msg = MagicMock(as2_from="ME", as2_to="YOU", message_id="msg-1")

        res = await service._save_transaction(
            mock_partnership,
            mock_as2_msg,
            b"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~",
        )
        assert res == "msg-1"
        mock_repo.create_edi_message.assert_awaited_once()
        mock_repo.publish_outbox_event.assert_awaited_once()
        args, kwargs = mock_repo.publish_outbox_event.call_args
        assert kwargs["idempotency_key"] == "msg-1"
        mock_session.commit.assert_awaited_once()
