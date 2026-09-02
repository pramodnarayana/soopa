import structlog
from edi.adapters.inbound.as2.mdn import build_mdn
from edi.application.dto import ProcessInboundAs2Command
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)
from edi.domain.exceptions import OrchestrationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from unified_api.adapters.inbound.http.dependencies.edi.services import get_as2_receiver_service

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Platform - AS2 Receive"])


@router.post("/as2/receive")
async def receive_as2_message(
    request: Request,
    service: ProcessInboundAs2MessageUseCase = Depends(get_as2_receiver_service),
) -> Response:
    """
    AS2 HTTP Adapter.
    Strictly handles HTTP parsing and delegates all business logic to the Application Service.
    """

    body_bytes = await request.body()
    headers = dict(request.headers)

    # Extract headers for MDN generation in case of failure
    as2_to_hdr = headers.get("as2-to") or headers.get("AS2-To")
    as2_from_hdr = headers.get("as2-from") or headers.get("AS2-From")
    msg_id_hdr = headers.get("message-id") or headers.get("Message-ID")

    try:
        # Delegate to the Hexagonal Architecture Use Case
        mdn_body, mdn_headers = await service.process_inbound_message(
            ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
        )
    except ValueError as e:
        logger.warning("Business logic rejection: {e}", e=e)
        if as2_to_hdr and as2_from_hdr and msg_id_hdr:
            error_msg = str(e).lower()
            if "decrypt" in error_msg:
                modifier = "error: decryption-failed"
            elif "authentic" in error_msg or "sign" in error_msg or "cert" in error_msg:
                modifier = "error: authentication-failed"
            elif "integr" in error_msg or "mic" in error_msg:
                modifier = "error: integrity-check-failed"
            else:
                modifier = "error: unexpected-processing-error"

            mdn = build_mdn(
                as2_to=as2_to_hdr,
                as2_from=as2_from_hdr,
                message_id=msg_id_hdr,
                disposition=f"automatic-action/MDN-sent-automatically; processed/{modifier}",
            )
            return Response(
                content=mdn.body,
                media_type=mdn.headers.get("Content-Type", "multipart/report"),
                headers=mdn.headers,
            )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OrchestrationError as e:
        logger.exception("Internal server error")

        if as2_to_hdr and as2_from_hdr and msg_id_hdr:
            mdn = build_mdn(
                as2_to=as2_to_hdr,
                as2_from=as2_from_hdr,
                message_id=msg_id_hdr,
                disposition="automatic-action/MDN-sent-automatically; processed/error: unexpected-processing-error",
            )
            return Response(
                content=mdn.body,
                media_type=mdn.headers.get("Content-Type", "multipart/report"),
                headers=mdn.headers,
            )
        raise HTTPException(status_code=500, detail="Internal server error") from e

    return Response(
        content=mdn_body,
        media_type=mdn_headers.get("Content-Type", "multipart/report"),
        headers=mdn_headers,
    )
