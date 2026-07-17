from unittest.mock import AsyncMock, MagicMock

import pytest
from api.dependencies import get_uow, require_platform_admin
from api.main import app
from fastapi.testclient import TestClient
from scheduler.domain.models import JobName


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    # Support async with
    uow.__aenter__.return_value = uow
    uow.__aexit__.return_value = None

    # Mock settings get/set
    uow.platform_settings = AsyncMock()
    uow.platform_settings.get_config.return_value = 60

    # Mock global session
    uow.global_session = AsyncMock()
    uow.global_session.begin_nested = MagicMock()
    uow.global_session.begin_nested.return_value.__aenter__ = AsyncMock()
    uow.global_session.begin_nested.return_value.__aexit__ = AsyncMock(return_value=None)

    # Setup execute return
    mock_result = MagicMock()
    mock_result.scalars().all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    uow.global_session.execute.return_value = mock_result

    return uow


@pytest.fixture
def client(mock_uow):
    app.dependency_overrides[get_uow] = lambda: mock_uow
    app.dependency_overrides[require_platform_admin] = lambda: 0
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_scheduler_list_jobs_empty(client):
    resp = client.get("/api/v1/platform/scheduler/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_scheduler_get_all_config(client):
    resp = client.get("/api/v1/platform/scheduler/config")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_scheduler_get_config(client):
    resp = client.get("/api/v1/platform/scheduler/config/some_config_key")
    assert resp.status_code == 200
    assert resp.json()["key"] == "some_config_key"


def test_scheduler_update_job_invalid_interval(client, mock_uow):
    import uuid
    from datetime import datetime

    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()
    mock_job.name = JobName.OUTBOX_SWEEPER
    mock_job.status = "PENDING"
    mock_job.next_run_at = datetime.now()
    mock_job.locked_at = None
    mock_job.locked_by = None
    mock_job.interval_seconds = 60
    mock_job.min_interval_seconds = 10
    mock_job.max_interval_seconds = 300
    mock_job.retry_count = 0
    mock_job.error_message = None
    mock_job.created_at = datetime.now()
    mock_job.updated_at = datetime.now()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_job
    mock_uow.global_session.execute.return_value = mock_result

    resp = client.put(
        "/api/v1/platform/scheduler/jobs/outbox_sweeper",
        json={"interval_seconds": -5},
    )
    assert resp.status_code == 422


def test_scheduler_create_job(client, mock_uow):
    resp = client.post(
        "/api/v1/platform/scheduler/jobs",
        json={"name": "test_job", "interval_seconds": 60, "payload": {}},
    )
    assert resp.status_code == 200
    assert mock_uow.global_session.add.called
    assert resp.json()["name"] == "test_job"


def test_scheduler_create_job_already_exists(client, mock_uow):
    from sqlalchemy.exc import IntegrityError

    mock_uow.global_session.flush.side_effect = IntegrityError("mock", {}, Exception())

    resp = client.post(
        "/api/v1/platform/scheduler/jobs",
        json={"name": "test_job"},
    )
    assert resp.status_code == 409


def test_scheduler_delete_job(client, mock_uow):
    mock_job = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_job
    mock_uow.global_session.execute.return_value = mock_result

    resp = client.delete("/api/v1/platform/scheduler/jobs/test_job")
    assert resp.status_code == 204
    assert mock_uow.global_session.delete.called


def test_scheduler_delete_job_not_found(client, mock_uow):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_uow.global_session.execute.return_value = mock_result

    resp = client.delete("/api/v1/platform/scheduler/jobs/test_job")
    assert resp.status_code == 404
