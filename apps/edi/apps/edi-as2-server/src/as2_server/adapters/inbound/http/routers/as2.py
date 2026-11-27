from typing import Annotated

from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2Command,
    ProcessInboundAs2MessageUseCase,
)
from edi.domain.exceptions import As2MdnDispositionModifier, OrchestrationError
from edi.domain.partner.as2.protocol import build_mdn
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

    as2_to_hdr = request.headers.get("as2-to")
    as2_from_hdr = request.headers.get("as2-from")
    msg_id_hdr = request.headers.get("message-id")

    with tracer.start_span("as2.process"):
        try:
            result = await use_case.process_inbound_message(
                ProcessInboundAs2Command(headers=headers, body_bytes=body_bytes)
            )
        except OrchestrationError as exc:
            logger.exception(
                "as2_internal_server_error",
                as2_from=as2_from_hdr,
                as2_to=as2_to_hdr,
                message_id=msg_id_hdr,
            )
            if as2_to_hdr and as2_from_hdr and msg_id_hdr:
                mdn = build_mdn(
                    as2_to=as2_to_hdr,
                    as2_from=as2_from_hdr,
                    message_id=msg_id_hdr,
                    disposition=(
                        "automatic-action/MDN-sent-automatically; "
                        f"processed/{As2MdnDispositionModifier.UNEXPECTED_PROCESSING_ERROR.value}"
                    ),
                    human_readable_text="Internal server error while processing AS2 message.",
                )
                return Response(
                    content=mdn.body,
                    media_type=mdn.headers.get("Content-Type", "multipart/report"),
                    headers=mdn.headers,
                )
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    if result.is_err:
        err = result.unwrap_err()
        logger.error(
            "as2_inbound_rejected",
            error_code=err.code.value,
            mdn_modifier=err.mdn_modifier.value,
            error=err.message,
            **err.details,
        )
        if as2_to_hdr and as2_from_hdr and msg_id_hdr:
            mdn = build_mdn(
                as2_to=as2_to_hdr,
                as2_from=as2_from_hdr,
                message_id=msg_id_hdr,
                disposition=(
                    f"automatic-action/MDN-sent-automatically; processed/{err.mdn_modifier.value}"
                ),
                human_readable_text=err.safe_mdn_text,
            )
            return Response(
                content=mdn.body,
                media_type=mdn.headers.get("Content-Type", "multipart/report"),
                headers=mdn.headers,
            )
        raise HTTPException(status_code=400, detail=err.message)

    processed = result.unwrap()
    if processed.routing_error is None:
        logger.info(
            "as2_inbound_accepted",
            edi_message_id=processed.edi_message_id,
            tenant_id=processed.tenant_id,
            isa_sender=processed.isa_sender,
            isa_receiver=processed.isa_receiver,
            as2_from=as2_from_hdr,
            as2_to=as2_to_hdr,
            message_id=msg_id_hdr,
        )
    else:
        routing_err = processed.routing_error
        logger.error(
            "as2_inbound_received_with_routing_error",
            error_code=routing_err.code.value,
            error=routing_err.message,
            edi_message_id=processed.edi_message_id,
            tenant_id=processed.tenant_id,
            **routing_err.details,
        )
    return Response(
        content=processed.mdn_body,
        media_type=processed.mdn_headers.get("Content-Type", "multipart/report"),
        headers=processed.mdn_headers,
    )
