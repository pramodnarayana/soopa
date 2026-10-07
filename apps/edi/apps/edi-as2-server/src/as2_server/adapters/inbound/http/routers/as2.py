from typing import Annotated

from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2Command,
    ProcessInboundAs2MessageUseCase,
)
from edi.domain.exceptions import OrchestrationError
from edi.domain.services.as2_protocol import build_mdn
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from observability import ObservabilityProvider

from .....dependencies import get_receive_as2_use_case

router = APIRouter(tags=["as2"])

ProcessInboundAS2UseCaseDep = Annotated[
    ProcessInboundAs2MessageUseCase, Depends(get_receive_as2_use_case)
]


@router.post("/as2/inbox")
async def receive_as2(
    request: Request,
    use_case: ProcessInboundAS2UseCaseDep,
) -> Response:
    tracer = ObservabilityProvider.tracer()
    logger = ObservabilityProvider.logger(__name__)

    body_bytes = await request.body()
    headers = dict(request.headers)

    as2_to_hdr = headers.get("as2-to") or headers.get("AS2-To")
    as2_from_hdr = headers.get("as2-from") or headers.get("AS2-From")
    msg_id_hdr = headers.get("message-id") or headers.get("Message-ID")

    with tracer.start_span("as2.process"):
        try:
            mdn_body, mdn_headers = await use_case.process_inbound_message(
                ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
            )
        except ValueError as e:
            logger.warning("as2_business_logic_rejection", error=str(e))
            if as2_to_hdr and as2_from_hdr and msg_id_hdr:
                error_msg = str(e).lower()
                if "decrypt" in error_msg:
                    modifier = "error: decryption-failed"
                elif "authentic" in error_msg or "sign" in error_msg or "cert" in error_msg:
                    modifier = "error: authentication-failed"
                elif "integr" in error_msg or "mic" in error_msg:
                    modifier = "error: integrity-check-failed"
                elif "partnership" in error_msg or "secure" in error_msg:
                    modifier = "error: insufficient-message-security"
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
            logger.exception("as2_internal_server_error")
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
