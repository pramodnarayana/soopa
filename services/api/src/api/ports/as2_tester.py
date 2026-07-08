from typing import Protocol


class AS2TesterPort(Protocol):
    async def test_connection(
        self,
        remote_url: str,
        as2_from: str,
        as2_to: str,
        local_private_key_pem: bytes | None,
        local_cert_pem: bytes | None,
        remote_cert_pem: bytes | None,
        encryption_algorithm: str,
        custom_payload: str | None = None,
    ) -> tuple[bool, str | None, str | None, str | None]:
        """
        Sends a synthetic AS2 ping to the remote partner's URL.

        Responsibility: transport only.
        Returns:
            (True, raw_mdn_disposition, sent_payload, raw_mdn)
            (False, error_reason, sent_payload, raw_mdn)

        The caller is responsible for interpreting the MDN disposition as a business success or failure.
        """
        ...
