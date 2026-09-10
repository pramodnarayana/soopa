"""Tenant-scoped notification template endpoints."""

import asyncio
import json
from typing import Any

import jinja2
import structlog
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from notification.adapters.outbound.template_renderer import Jinja2TemplateRenderer
from notification.bootstrap.container import Container
from notification.config import NotificationEngineSettings
from notification.domain.models import Channel, Template
from notification.ports.outbound.notification_templates_repository_port import (
    NotificationTemplatesRepositoryPort,
)
from pydantic import BaseModel, Field, field_validator

from unified_api.adapters.inbound.http.guards.notification_auth_guard import (
    assert_tenant_authorized,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["notification-templates"])
_RENDER_SEMAPHORE = asyncio.Semaphore(10)


class TemplateResponse(BaseModel):
    """Read DTO for a notification template."""

    id: str
    tenant_id: str
    name: str
    event_type: str
    channel: str
    subject_template: str | None
    body_template: str
    is_active: bool


class UpsertTemplateRequest(BaseModel):
    """Write DTO for creating or replacing a notification template."""

    name: str
    event_type: str
    channel: str
    subject_template: str | None = None
    body_template: str
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty.")
        return value.strip()

    @field_validator("channel")
    @classmethod
    def channel_must_be_valid(cls, value: str) -> str:
        valid = {channel.value for channel in Channel}
        if value not in valid:
            raise ValueError(f"Invalid channel '{value}'. Must be one of {valid}.")
        return value

    @field_validator("body_template")
    @classmethod
    def body_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body_template must not be empty.")
        return value


class PreviewTemplateRequest(BaseModel):
    """Request body for live Jinja2 preview in the template editor."""

    subject_template: str | None = None
    body_template: str
    fake_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("body_template")
    @classmethod
    def body_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body_template must not be empty.")
        return value


class PreviewTemplateResponse(BaseModel):
    """Rendered output from the Jinja2 sandbox preview."""

    rendered_subject: str | None
    rendered_body: str


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
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),
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
    repo: NotificationTemplatesRepositoryPort = Depends(Provide[Container.template_repository]),
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
    summary="Render a draft Jinja2 template against a fake payload (live preview)",
)
@inject
async def preview_template(
    tenant_id: str,
    body: PreviewTemplateRequest,
    request: Request,
    renderer: Jinja2TemplateRenderer = Depends(Provide[Container.template_renderer]),
    settings: NotificationEngineSettings = Depends(Provide[Container.engine_settings]),
) -> PreviewTemplateResponse:
    assert_tenant_authorized(request, tenant_id)

    if len(body.body_template) > settings.max_template_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Template body exceeds maximum size of "
                f"{settings.max_template_size_chars} characters"
            ),
        )
    if body.subject_template and len(body.subject_template) > settings.max_template_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Subject template exceeds maximum size of "
                f"{settings.max_template_size_chars} characters"
            ),
        )

    serialized_payload = json.dumps(body.fake_payload)
    if len(serialized_payload) > settings.max_payload_size_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fake payload exceeds maximum size of {settings.max_payload_size_chars} characters",
        )

    try:
        async with _RENDER_SEMAPHORE:
            rendered_body = await asyncio.wait_for(
                asyncio.to_thread(renderer.render, body.body_template, body.fake_payload),
                timeout=settings.render_timeout_seconds,
            )
            rendered_subject = None
            if body.subject_template:
                rendered_subject = await asyncio.wait_for(
                    asyncio.to_thread(renderer.render, body.subject_template, body.fake_payload),
                    timeout=settings.render_timeout_seconds,
                )
    except TimeoutError as exc:
        logger.warning("template_render_timeout", tenant_id=tenant_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template rendering timed out. Please simplify the template.",
        ) from exc
    except jinja2.TemplateError as exc:
        logger.exception(
            "template_render_error",
            tenant_id=tenant_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template rendering failed. Please check your template syntax.",
        ) from exc

    return PreviewTemplateResponse(
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
    )
