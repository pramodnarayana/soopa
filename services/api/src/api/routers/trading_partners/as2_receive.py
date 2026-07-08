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

    try:
        # Delegate to the Hexagonal Architecture Use Case
        mdn_body, mdn_headers = await service.process_inbound_message(
            headers=headers, body_bytes=body_bytes
        )
    except ValueError as e:
        logger.warning(f"Business logic rejection: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Internal server error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    return Response(
        content=mdn_body,
        media_type=mdn_headers.get("Content-Type", "multipart/report"),
        headers=mdn_headers,
    )
