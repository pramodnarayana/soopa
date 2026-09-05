from edi.domain.models.as2 import AS2MDN


def render_mdn_report(mdn: AS2MDN, boundary: str = "----=_MDNBoundary") -> bytes:
    """
    Renders the MDN dataclass into a raw HTTP multipart/report payload.
    This is an HTTP transport concern, so it belongs in the AS2 Server adapters.
    """
    disp_val = mdn.disposition.value if hasattr(mdn.disposition, "value") else str(mdn.disposition)

    if "decryption-failed" in disp_val:
        text = "The AS2 message failed decryption."
    elif "authentication-failed" in disp_val:
        text = "The AS2 message failed authentication."
    elif "processed" in disp_val:
        text = "The AS2 message has been processed."
    else:
        text = "The AS2 message processing failed."

    report = (
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/disposition-notification\r\n\r\n"
        f"Original-Message-ID: <{mdn.original_message_id}>\r\n"
        f"Disposition: {disp_val}\r\n"
    )

    if mdn.mic:
        report += f"Received-content-MIC: {mdn.mic}\r\n"

    report += f"\r\n--{boundary}--\r\n"

    return report.encode("utf-8")
