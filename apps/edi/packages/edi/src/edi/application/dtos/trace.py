from dataclasses import dataclass

from edi.application.dtos.transactions import ApiGatewayDTO, EdiJsonDTO, EdiMessageDTO


@dataclass(frozen=True, kw_only=True)
class EdiTraceDTO:
    """Composed lifecycle view of a full trace: EdiMessage + EdiJson(s) + ApiGateway(s)."""

    edi_message: EdiMessageDTO
    edi_jsons: list[EdiJsonDTO]
    api_gateways: list[ApiGatewayDTO]
