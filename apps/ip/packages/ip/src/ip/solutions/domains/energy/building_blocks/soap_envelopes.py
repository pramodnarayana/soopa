"""Reusable SOAP envelope generators for XML AMI protocols."""

from __future__ import annotations


def build_soap_envelope(service_namespace: str, operation_name: str, payload_xml: str) -> str:
    """Standard SOAP 1.2 envelope builder for XML AMI protocols."""
    return (
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:ns="{service_namespace}">\n'
        f"    <soapenv:Header/>\n"
        f"    <soapenv:Body>\n"
        f"        <ns:{operation_name}>\n"
        f"            {payload_xml}\n"
        f"        </ns:{operation_name}>\n"
        f"    </soapenv:Body>\n"
        f"</soapenv:Envelope>"
    )
