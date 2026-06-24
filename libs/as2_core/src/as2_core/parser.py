"""
Pure logic for parsing AS2 raw HTTP requests into AS2Message dataclasses.
"""

from .message import AS2Message


def parse_as2_request(headers: dict[str, str], raw_body: bytes) -> AS2Message:
    """
    Parses raw HTTP headers and body into an AS2Message.
    Identifies encryption, signing, and compression.
    """
    as2_from = headers.get("as2-from", "").strip(' "')
    as2_to = headers.get("as2-to", "").strip(' "')
    message_id = headers.get("message-id", "").strip(" <>")
    content_type = headers.get("content-type", "").lower()

    if not as2_from or not as2_to or not message_id:
        raise ValueError("Missing mandatory AS2 headers (as2-from, as2-to, message-id).")

    is_encrypted = "application/pkcs7-mime" in content_type and "enveloped-data" in content_type
    is_signed = "multipart/signed" in content_type or "application/pkcs7-signature" in content_type
    is_compressed = "application/pkcs7-mime" in content_type and "compressed-data" in content_type

    # The payload is initially the raw body.
    # If encrypted, it needs to be decrypted via smime.py before further processing.
    # If signed, it needs to be verified.

    return AS2Message(
        message_id=message_id,
        as2_from=as2_from,
        as2_to=as2_to,
        headers=headers,
        payload=raw_body,
        is_encrypted=is_encrypted,
        is_signed=is_signed,
        is_compressed=is_compressed,
        raw_mime=raw_body,
    )
