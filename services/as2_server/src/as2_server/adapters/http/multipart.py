from as2_core import AS2MDN


def render_mdn_report(mdn: AS2MDN, boundary: str = "----=_MDNBoundary") -> bytes:
    """
    Renders the MDN dataclass into a raw HTTP multipart/report payload.
    This is an HTTP transport concern, so it belongs in the AS2 Server adapters.
    """
    report = (
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=us-ascii\r\n\r\n"
        f"The AS2 message has been processed.\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/disposition-notification\r\n\r\n"
        f"Original-Message-ID: <{mdn.original_message_id}>\r\n"
        f"Disposition: {mdn.disposition.value if hasattr(mdn.disposition, 'value') else mdn.disposition}\r\n"
    )

    if mdn.mic:
        report += f"Received-content-MIC: {mdn.mic}\r\n"

    report += f"--{boundary}--\r\n"

    return report.encode("utf-8")
