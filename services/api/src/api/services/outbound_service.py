import json
import logging
import uuid
from typing import Any, cast
from uuid import UUID

from api.core.uow import UnitOfWork
from api.ports.repository import ControlPlaneRepositoryPort, DataPlaneRepositoryPort
from pipeline.core.metadata_extractor import MetadataExtractorService

logger = logging.getLogger(__name__)


class OutboundService:
    """
    Application Service (Use Case Layer) for handling outbound API requests.
    Strictly follows Single Responsibility Principle and encapsulates business logic.
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.extractor = MetadataExtractorService()

    async def process_outbound_message(
        self,
        tenant_id: int,
        trading_partner_id: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        transaction_type: str | None = None,
    ) -> UUID:
        """
        Orchestrates the outbound API flow:
        1. Validate Partnership by trading_partner_id.
        2. Extract Business Metadata.
        3. Save to EdiJson and ApiGateway.
        4. Drop Outbox event for Worker.

        Returns:
            UUID: The generated trace_id for tracking.
        """
        async with self.uow:
            control_plane = cast(ControlPlaneRepositoryPort, self.uow.control_plane)
            data_plane = cast(DataPlaneRepositoryPort, self.uow.data_plane)

            # 1. Validate Route by human-readable trading_partner_id (from ControlPlane/global DB)
            logger.info(f"Received outbound transaction request for partner: {trading_partner_id}")
            route = await control_plane.get_outbound_route_by_trading_partner_id(
                tenant_id=tenant_id, trading_partner_id=trading_partner_id
            )
            if not route:
                logger.error(f"Outbound route '{trading_partner_id}' not found or not active")
                raise ValueError(f"Outbound route '{trading_partner_id}' not found or not active")

            logger.info(f"Resolved OutboundRoute: {route.id} (Standard: {route.default_standard})")

            # 2. Resolve transaction_type from payload if not provided explicitly
            if not transaction_type:
                first_payload = (
                    payload[0]
                    if isinstance(payload, list) and payload
                    else (payload if isinstance(payload, dict) else {})
                )
                transaction_type = first_payload.get("transaction_type")
                if not transaction_type:
                    heading = first_payload.get("heading", {})
                    for key in heading:
                        if key.startswith("transaction_set_header_ST"):
                            transaction_type = heading[key].get("transaction_set_identifier_code")
                            break
                if not transaction_type:
                    # Try ST segment directly (for raw transaction payloads)
                    st = first_payload.get("ST", {})
                    if st:
                        transaction_type = st.get("ST01")

            if not transaction_type:
                transaction_type = route.transaction_type

            if not transaction_type:
                logger.error(
                    "Could not determine transaction_type from payload or route configuration."
                )
                raise ValueError("Transaction type could not be determined")

            business_metadata = {}
            if isinstance(payload, dict):
                business_metadata = self.extractor.extract(transaction_type or "", payload)
            elif isinstance(payload, list) and len(payload) > 0:
                business_metadata = self.extractor.extract(transaction_type or "", payload[0])

            # 3. Create Trace ID
            trace_id = uuid.uuid4()
            logger.info(f"Generated Trace ID: {trace_id}")

            # 4. Save to ApiGateway (Logging)
            api_gateway_payload = {
                "trace_id": trace_id,
                "direction": "OUTBOUND",
                "transaction_type": transaction_type,
                "payload": payload,
                "response": json.dumps({"status": "ACCEPTED", "trace_id": str(trace_id)}),
                "http_status_code": 202,
                "status": "ACCEPTED",
            }
            await data_plane.create_api_gateway(tenant_id=tenant_id, payload=api_gateway_payload)

            # 5. Save to EdiJson
            sender_id = route.isa_sender_id
            receiver_id = route.isa_receiver_id

            # If payload doesn't already have an AST wrapper, wrap it in a Bots AST envelope
            edi_json_data = payload
            if (
                isinstance(payload, dict)
                and "interchange_ISA" not in payload
                and "interchange_UNB" not in payload
            ) or isinstance(payload, list):
                from transformer.domain.envelope_factory import EnvelopeFactory

                route_config = {
                    "default_standard": route.default_standard,
                    "default_version": route.default_version,
                    "transaction_type": transaction_type or "",
                    "isa_sender_qualifier": route.isa_sender_qualifier,
                    "isa_sender_id": route.isa_sender_id,
                    "isa_receiver_qualifier": route.isa_receiver_qualifier,
                    "isa_receiver_id": route.isa_receiver_id,
                    "gs_sender_id": route.gs_sender_id,
                    "gs_receiver_id": route.gs_receiver_id,
                    "environment": "P",  # In future, derive from tenant/route config
                }

                logger.info("Applying dynamic EnvelopeFactory AST wrapper to payload...")
                edi_json_data = EnvelopeFactory.build_ast(route_config, payload)
                logger.info(
                    f"Successfully wrapped payload in {route.default_standard.upper()} AST."
                )

            edi_json_payload = {
                "trace_id": trace_id,
                "direction": "OUTBOUND",
                "outbound_route_id": route.id,
                "transaction_type": transaction_type,
                "standard": route.default_standard,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "gs_sender_id": route.gs_sender_id,
                "gs_receiver_id": route.gs_receiver_id,
                "business_metadata": business_metadata,
                "payload": edi_json_data,
                "status": "PENDING",
            }
            edi_json_id = await data_plane.create_edi_json(
                tenant_id=tenant_id, payload=edi_json_payload
            )

            # 6. Create Outbox Event
            outbox_payload = {
                "edi_json_id": str(edi_json_id),
                "trace_id": str(trace_id),
                "outbound_route_id": str(route.id),
                "status": "RECEIVED",
            }
            await data_plane.create_outbox_event(
                tenant_id=tenant_id,
                event_type="json.received",
                payload=outbox_payload,
            )

            logger.info(
                f"Committed Outbound Transaction {trace_id} to database. Sent outbox event."
            )
            await self.uow.commit()
            return trace_id
