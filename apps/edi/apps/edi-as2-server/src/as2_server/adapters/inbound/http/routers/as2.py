from typing import Annotated, Any

from edi.domain.services.as2_protocol import parse_as2_request
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from observability import ObservabilityProvider

from .....application.use_cases.receive_as2 import ReceiveAS2UseCase
from .....dependencies import get_receive_as2_use_case
from ..multipart import render_mdn_report

router = APIRouter(tags=["as2"])

ReceiveAS2UseCaseDep = Annotated[ReceiveAS2UseCase, Depends(get_receive_as2_use_case)]


@router.post("/as2")
async def receive_as2(
    request: Request,
    use_case: ReceiveAS2UseCaseDep,
) -> Any:
    tracer = ObservabilityProvider.tracer()
    logger = ObservabilityProvider.logger(__name__)

    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    with tracer.start_span("as2.parse") as span:
        try:
            as2_msg = parse_as2_request(headers, raw_body)
            span.set_attribute("as2.message_id", as2_msg.message_id)
        except ValueError as e:
            logger.warning("as2_parse_failed", error=str(e))
            raise HTTPException(status_code=400, detail=str(e)) from e

    mdn = await use_case.execute(as2_msg)

    report_bytes = render_mdn_report(mdn)

    return Response(
        content=report_bytes,
        status_code=200,
        media_type='multipart/report; report-type=disposition-notification; boundary="----=_MDNBoundary"',
        headers={"AS2-Version": "1.2", "EDIINT-Features": "multiple-attachments"},
    )
