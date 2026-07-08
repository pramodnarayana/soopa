import logging

from database.session import get_global_session
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_vault
from api.ports.vault import VaultPort
from api.services.as2_receive_service import As2ReceiveService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Platform - AS2 Receive"])


@router.post("/as2/receive")
async def receive_as2_message(
    request: Request,
    global_session: AsyncSession = Depends(get_global_session),
    vault: VaultPort = Depends(get_vault),
) -> Response:
    """
    AS2 HTTP Adapter.
    Strictly handles HTTP parsing and delegates all business logic to the Application Service.
    """
    body_bytes = await request.body()
    headers = dict(request.headers)

    # Instantiate the application service (Use Case)
    service = As2ReceiveService(
        global_session=global_session, vault=vault, db_router=request.app.state.db_router
    )

    # Extract headers for MDN generation in case of failure
    as2_to_hdr = headers.get("as2-to") or headers.get("AS2-To")
    as2_from_hdr = headers.get("as2-from") or headers.get("AS2-From")
    msg_id_hdr = headers.get("message-id") or headers.get("Message-ID")

    try:
        # Delegate to the Hexagonal Architecture Use Case
        mdn_body, mdn_headers = await service.process_inbound_message(
            headers=headers, body_bytes=body_bytes
        )
    except ValueError as e:
        logger.warning(f"Business logic rejection: {e}")
        if as2_to_hdr and as2_from_hdr and msg_id_hdr:
            from as2_core import build_mdn

            mdn = build_mdn(
                as2_to=as2_to_hdr,
                as2_from=as2_from_hdr,
                message_id=msg_id_hdr,
                disposition=f"automatic-action/MDN-sent-automatically; processed/error: {e}",
            )
            return Response(
                content=mdn.body,
                media_type=mdn.headers.get("Content-Type", "multipart/report"),
                headers=mdn.headers,
            )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Internal server error: {e}")
        if as2_to_hdr and as2_from_hdr and msg_id_hdr:
            from as2_core import build_mdn

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
