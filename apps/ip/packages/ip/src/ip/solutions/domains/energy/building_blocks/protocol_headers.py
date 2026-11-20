"""Reusable HTTP and SOAP protocol header factories for Energy utility vendors."""

from __future__ import annotations

from ip.sdk import build_json_headers


def build_landis_headers(api_version: str = "v2") -> dict[str, str]:
    """Builds standard HTTP headers for Landis+Gyr Gridstream AMI APIs."""
    return {
        **build_json_headers(),
        "X-API-Version": api_version,
        "X-Client-System": "SOOPA-IP",
    }


def build_soap_headers(soap_action: str) -> dict[str, str]:
    """Builds standard SOAP 1.1 / 1.2 headers for XML-based AMI systems."""
    return {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{soap_action}"',
    }


def build_sap_odata_headers(csrf_token: str | None = None) -> dict[str, str]:
    """Builds standard HTTP headers for SAP IS-U OData mutations."""
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    return headers
