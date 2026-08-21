from dataclasses import dataclass
from typing import Any

from edi.application.use_cases.routing_resolver import RoutingResolutionService
from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


@dataclass
class TransactionDetailResult:
    edi_message: dict[str, Any]
    edi_json: list[dict[str, Any]]
    api_gateway: list[dict[str, Any]]
    trading_partner_name: str | None


class TransactionService:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def replay_transaction(self, tenant_id: str, trace_id: str, tier: str) -> None:
        """
        Trigger an asynchronous replay of a transaction at the specified tier.
        Publishes an outbox event.
        """
        # Validate existence
        result = await self.uow.transactions.get_transaction(tenant_id, trace_id)
        if not result or not result.edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        # Publish Outbox event for the Orchestrator Worker
        import uuid

        await self.uow.data_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type="edi.transaction.replay_requested",
            payload={
                "trace_id": trace_id,
                "tier": tier,
            },
            idempotency_key=f"replay_{trace_id}_{uuid.uuid4().hex}",
        )

    async def bulk_replay_transactions(
        self, tenant_id: str, trace_ids: list[str], tier: str, command_key: str | None = None
    ) -> int:
        """
        Trigger asynchronous replay of multiple transactions at the specified tier.
        Publishes multiple outbox events atomically within the current UOW.
        Returns the count of unique trace IDs processed.
        """
        if not trace_ids:
            return 0

        import uuid

        # 0. Deduplicate trace IDs
        unique_trace_ids = list(dict.fromkeys(trace_ids))

        # 1. Bulk Existence Check
        existing_trace_ids = await self.uow.transactions.get_existing_trace_ids(
            tenant_id, unique_trace_ids
        )
        missing_trace_ids = set(unique_trace_ids) - existing_trace_ids
        if missing_trace_ids:
            # For simplicity, we just raise for the first missing one, or could raise a bulk error
            raise TransactionNotFoundError(trace_id=next(iter(missing_trace_ids)))

        # 2. Construct Bulk Events
        events = []
        for trace_id in unique_trace_ids:
            if command_key:
                idem_key = f"replay_{command_key}_{trace_id}"
            else:
                idem_key = f"replay_{trace_id}_{uuid.uuid4().hex}"

            events.append(
                {
                    "event_type": "edi.transaction.replay_requested",
                    "payload": {
                        "trace_id": trace_id,
                        "tier": tier,
                    },
                    "idempotency_key": idem_key,
                }
            )

        # 3. Bulk Insert Outbox Events
        await self.uow.data_plane_outbox.publish_outbox_events_bulk(
            tenant_id=tenant_id, events=events
        )

        return len(unique_trace_ids)

    async def get_transaction(
        self,
        tenant_id: str,
        trace_id: str,
        routing_resolver: RoutingResolutionService,
    ) -> TransactionDetailResult:
        """
        Get the full deep-dive payload for a single trace lifecycle spanning EdiMessage, EdiJson, and ApiGateway.
        """
        result = await self.uow.transactions.get_transaction(tenant_id, trace_id)
        if not result or not result.edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        msg = result.edi_message
        edi_msg_dict = {
            "id": str(msg.id),
            "trace_id": str(msg.trace_id),
            "direction": msg.direction,
            "connection_type": msg.connection_type,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "gs_sender_id": msg.gs_sender_id,
            "gs_receiver_id": msg.gs_receiver_id,
            "status": msg.status,
            "edi_data": msg.edi_data,
            "parent_trace_id": msg.parent_trace_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }

        edi_jsons = []
        for j in result.edi_jsons or []:
            edi_jsons.append(
                {
                    "id": str(j.id),
                    "transaction_type": j.transaction_type,
                    "sender_id": j.sender_id,
                    "receiver_id": j.receiver_id,
                    "gs_sender_id": j.gs_sender_id,
                    "gs_receiver_id": j.gs_receiver_id,
                    "business_metadata": j.business_metadata,
                    "payload": j.payload,
                    "status": j.status,
                    "parent_trace_id": j.parent_trace_id,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
            )

        apigws = []
        for gw in result.api_gateways or []:
            apigws.append(
                {
                    "id": str(gw.id),
                    "webhook_url": gw.webhook_url,
                    "http_status_code": gw.http_status_code,
                    "payload": gw.payload,
                    "response": gw.response,
                    "status": gw.status,
                    "parent_trace_id": gw.parent_trace_id,
                    "created_at": gw.created_at.isoformat() if gw.created_at else None,
                }
            )

        trading_partner_name, new_conn_type = await routing_resolver.resolve_routing_context(
            msg, result.edi_jsons or []
        )
        if new_conn_type and edi_msg_dict.get("connection_type") in ("UNKNOWN", None):
            edi_msg_dict["connection_type"] = new_conn_type

        return TransactionDetailResult(
            edi_message=edi_msg_dict,
            edi_json=edi_jsons,
            api_gateway=apigws,
            trading_partner_name=trading_partner_name,
        )
