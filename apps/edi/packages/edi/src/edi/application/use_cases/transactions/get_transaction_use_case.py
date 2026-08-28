from dataclasses import dataclass
from typing import Any

from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


@dataclass
class TransactionDetailResult:
    edi_message: dict[str, Any]
    edi_json: list[dict[str, Any]]
    api_gateway: list[dict[str, Any]]
    trading_partner_name: str | None


class GetTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def get_transaction(
        self, tenant_id: str, trace_id: str, routing_resolver: Any = None
    ) -> TransactionDetailResult:
        """
        Get details for a specific transaction trace ID.
        """
        result = await self.uow.transactions.get_transaction(tenant_id, trace_id)
        if not result or not result.edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        edi_msg_dict = {
            "id": str(result.edi_message.id),
            "trace_id": str(result.edi_message.trace_id),
            "direction": result.edi_message.direction,
            "connection_type": result.edi_message.connection_type,
            "sender_id": result.edi_message.sender_id,
            "receiver_id": result.edi_message.receiver_id,
            "gs_sender_id": result.edi_message.gs_sender_id,
            "gs_receiver_id": result.edi_message.gs_receiver_id,
            "status": result.edi_message.status,
            "edi_data": result.edi_message.edi_data,
            "parent_trace_id": getattr(result.edi_message, "parent_trace_id", None),
            "created_at": result.edi_message.created_at.isoformat()
            if result.edi_message.created_at
            else None,
        }

        edi_jsons = []
        for j in getattr(result, "edi_jsons", []):
            edi_jsons.append(
                {
                    "id": str(j.id),
                    "transaction_type": j.transaction_type,
                    "sender_id": j.sender_id,
                    "receiver_id": j.receiver_id,
                    "gs_sender_id": getattr(j, "gs_sender_id", None),
                    "gs_receiver_id": getattr(j, "gs_receiver_id", None),
                    "status": j.status,
                    "business_metadata": j.business_metadata,
                    "payload": j.payload,
                    "parent_trace_id": getattr(j, "parent_trace_id", None),
                    "created_at": j.created_at.isoformat()
                    if getattr(j, "created_at", None)
                    else None,
                }
            )

        apigws = []
        for gw in getattr(result, "api_gateways", []):
            apigws.append(
                {
                    "id": str(gw.id),
                    "webhook_url": gw.webhook_url,
                    "http_status_code": getattr(gw, "http_status_code", None),
                    "status": gw.status,
                    "payload": getattr(gw, "payload", None),
                    "response": gw.response,
                    "parent_trace_id": getattr(gw, "parent_trace_id", None),
                    "created_at": gw.created_at.isoformat()
                    if getattr(gw, "created_at", None)
                    else None,
                }
            )

        trading_partner_name = None
        if routing_resolver:
            trading_partner_name, new_conn_type = await routing_resolver.resolve_routing_context(
                result.edi_message, getattr(result, "edi_jsons", [])
            )
            if new_conn_type and edi_msg_dict.get("connection_type") in ("UNKNOWN", None):
                edi_msg_dict["connection_type"] = new_conn_type

        return TransactionDetailResult(
            edi_message=edi_msg_dict,
            edi_json=edi_jsons,
            api_gateway=apigws,
            trading_partner_name=trading_partner_name,
        )
