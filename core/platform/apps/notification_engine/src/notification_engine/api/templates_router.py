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

import asyncio
import json
import logging
from typing import Any

import jinja2
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from notification_engine.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification_engine.api.authorization import assert_tenant_authorized
from notification_engine.bootstrap.container import Container
from notification_engine.config import NotificationEngineSettings
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
    name: str
    event_type: str
    channel: str
    subject_template: str | None
    body_template: str
    is_active: bool


class UpsertTemplateRequest(BaseModel):
    """Write DTO for creating / replacing a notification template."""

    name: str
    event_type: str
    channel: str
    subject_template: str | None = None
    body_template: str
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty.")
        return v.strip()

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
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),  # noqa: B008
) -> list[Template]:
    assert_tenant_authorized(request, tenant_id)
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
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),  # noqa: B008
) -> Template:
    assert_tenant_authorized(request, tenant_id)
    return await repo.upsert_template(
        tenant_id=tenant_id,
        name=body.name,
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
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),  # noqa: B008
) -> None:
    assert_tenant_authorized(request, tenant_id)
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
    renderer: Jinja2TemplateRenderer = Depends(Provide[Container.template_renderer]),  # noqa: B008
    settings: NotificationEngineSettings = Depends(Provide[Container.engine_settings]),  # noqa: B008
) -> PreviewTemplateResponse:
    """
    Renders the draft template body and optional subject through the production-identical
    SandboxedEnvironment. SSTI attempts are rejected here, giving the editor real-time
    security feedback before any template is persisted.
    """
    assert_tenant_authorized(request, tenant_id)

    if len(body.body_template) > settings.max_template_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template body exceeds maximum size of {settings.max_template_size_chars} characters",
        )

    if body.subject_template and len(body.subject_template) > settings.max_template_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Subject template exceeds maximum size of {settings.max_template_size_chars} characters",
        )

    serialized_payload = json.dumps(body.mock_payload)
    if len(serialized_payload) > settings.max_payload_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mock payload exceeds maximum size of {settings.max_payload_size_chars} characters",
        )

    try:
        # Render in thread pool with timeout to prevent blocking and DoS
        rendered_body = await asyncio.wait_for(
            asyncio.to_thread(renderer.render, body.body_template, body.mock_payload),
            timeout=settings.render_timeout_seconds,
        )
        rendered_subject = None
        if body.subject_template:
            rendered_subject = await asyncio.wait_for(
                asyncio.to_thread(renderer.render, body.subject_template, body.mock_payload),
                timeout=settings.render_timeout_seconds,
            )
    except TimeoutError as exc:
        logger.warning(f"Template render timeout for tenant {tenant_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template rendering timed out. Please simplify the template.",
        ) from exc
    except jinja2.TemplateError as exc:
        # Catch specific Jinja2 rendering errors (TemplateSyntaxError, UndefinedError, etc.)
        logger.exception(f"Template render error for tenant {tenant_id}: {type(exc).__name__}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template rendering failed. Please check your template syntax.",
        ) from exc

    return PreviewTemplateResponse(
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
    )
