"""HTTP acknowledgment builders conforming to external vendor webhook contracts."""

from __future__ import annotations

from collections.abc import Mapping

from ip.engine.ports.outbound.inbound_ack_port import AckResponseDTO, InboundAckPort
from seedwork.domain.types import JsonValue


class StandardInboundAck(InboundAckPort):
    """Default generic acknowledgment builder returning 202 Accepted with JSON body."""

    def __init__(self, status_code: int = 202) -> None:
        self._status_code = status_code

    def build_ack(
        self,
        *,
        app_id: str,
        payload: JsonValue,
        headers: Mapping[str, str],
    ) -> AckResponseDTO:
        return AckResponseDTO(
            status_code=self._status_code,
            headers={"Content-Type": "application/json"},
            body={"status": "accepted"},
        )


JsonInboundAck = StandardInboundAck


class XmlSoapInboundAck(InboundAckPort):
    """Generic SOAP XML acknowledgment builder."""

    def __init__(
        self,
        soap_namespace: str = "http://schemas.xmlsoap.org/soap/envelope/",
        response_namespace: str = "http://schemas.xmlsoap.org/soap/envelope/",
        response_element: str = "notificationsResponse",
        ack_element: str = "Ack",
        ack_value: str = "true",
    ) -> None:
        self._soap_namespace = soap_namespace
        self._response_namespace = response_namespace
        self._response_element = response_element
        self._ack_element = ack_element
        self._ack_value = ack_value

    def build_ack(
        self,
        *,
        app_id: str,
        payload: JsonValue,
        headers: Mapping[str, str],
    ) -> AckResponseDTO:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<soapenv:Envelope xmlns:soapenv="{self._soap_namespace}">\n'
            "  <soapenv:Body>\n"
            f'    <{self._response_element} xmlns="{self._response_namespace}">\n'
            f"      <{self._ack_element}>{self._ack_value}</{self._ack_element}>\n"
            f"    </{self._response_element}>\n"
            "  </soapenv:Body>\n"
            "</soapenv:Envelope>"
        )
        return AckResponseDTO(
            status_code=200,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            body=body,
        )
