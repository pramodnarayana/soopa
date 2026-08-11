"""
Notification Templates Router.

Exposes CRUD endpoints for tenant-scoped Jinja2 notification templates.
Each template is bound to a (event_type, channel) pair and contains a
Jinja2 body and an optional subject line.

The /preview endpoint renders a draft template through the same production
SandboxedEnvironment — SSTI attacks are caught here in real-time.

Authorization: Every endpoint validates the caller is authorized for the
requested tenant_id using the resolved IdentityContext from the middleware.
"""

import logging
from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from notification_engine.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification_engine.bootstrap.container import Container
from notification_engine.domain.models import Channel, Template
from notification_engine.ports.interfaces import NotificationTemplatesRepositoryPort

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["notification-templates"],
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TemplateResponse(BaseModel):
    """Read DTO for a notification template — no ORM model leakage."""

    id: str
    tenant_id: str
    event_type: str
    channel: str
    subject_template: str | None
    body_template: str
    is_active: bool


class UpsertTemplateRequest(BaseModel):
    """Write DTO for creating / replacing a notification template."""

    event_type: str
    channel: str
    subject_template: str | None = None
    body_template: str
    is_active: bool = True

    @field_validator("channel")
    @classmethod
    def channel_must_be_valid(cls, v: str) -> str:
        valid = {c.value for c in Channel}
        if v not in valid:
            raise ValueError(f"Invalid channel '{v}'. Must be one of {valid}.")
        return v

    @field_validator("body_template")
    @classmethod
    def body_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_template must not be empty.")
        return v


class PreviewTemplateRequest(BaseModel):
    """Request body for live Jinja2 preview in the template editor."""

    subject_template: str | None = None
    body_template: str
    mock_payload: dict[str, Any] = {}

    @field_validator("body_template")
    @classmethod
    def body_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_template must not be empty.")
        return v


class PreviewTemplateResponse(BaseModel):
    """Rendered output from the Jinja2 sandbox preview."""

    rendered_subject: str | None
    rendered_body: str


# ---------------------------------------------------------------------------
# Authorization helper (shared with preferences_router — candidate for extraction)
# ---------------------------------------------------------------------------


def _assert_tenant_authorized(request: Request, tenant_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity is not authorized to access
    the requested tenant. Guards all tenant-scoped endpoints against IDOR.
    """
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    authorized: set[str] = getattr(identity, "authorized_tenants", set())
    if tenant_id not in authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this tenant's notification templates.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/templates",
    response_model=list[TemplateResponse],
    status_code=status.HTTP_200_OK,
    summary="List all notification templates for a tenant",
)
@inject
async def list_templates(
    tenant_id: str,
    request: Request,
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),
) -> list[Template]:
    _assert_tenant_authorized(request, tenant_id)
    return await repo.list_templates(tenant_id)


@router.put(
    "/{tenant_id}/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert a notification template for a (event_type, channel) pair",
)
@inject
async def upsert_template(
    tenant_id: str,
    body: UpsertTemplateRequest,
    request: Request,
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),
) -> Template:
    _assert_tenant_authorized(request, tenant_id)
    return await repo.upsert_template(
        tenant_id=tenant_id,
        event_type=body.event_type,
        channel=body.channel,
        subject_template=body.subject_template,
        body_template=body.body_template,
        is_active=body.is_active,
    )


@router.delete(
    "/{tenant_id}/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification template",
)
@inject
async def delete_template(
    tenant_id: str,
    template_id: str,
    request: Request,
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),
) -> None:
    _assert_tenant_authorized(request, tenant_id)
    deleted = await repo.delete_template(tenant_id=tenant_id, template_id=template_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found",
        )


@router.post(
    "/{tenant_id}/templates/preview",
    response_model=PreviewTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Render a draft Jinja2 template against a mock payload (live preview)",
)
@inject
async def preview_template(
    tenant_id: str,
    body: PreviewTemplateRequest,
    request: Request,
    renderer: Jinja2TemplateRenderer = Depends(Provide[Container.template_renderer]),
) -> PreviewTemplateResponse:
    """
    Renders the draft template body and optional subject through the production-identical
    SandboxedEnvironment. SSTI attempts are rejected here, giving the editor real-time
    security feedback before any template is persisted.
    """
    _assert_tenant_authorized(request, tenant_id)
    try:
        rendered_body = renderer.render(body.body_template, body.mock_payload)
        rendered_subject = (
            renderer.render(body.subject_template, body.mock_payload)
            if body.subject_template
            else None
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template render error: {exc}",
        ) from exc

    return PreviewTemplateResponse(
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
    )
