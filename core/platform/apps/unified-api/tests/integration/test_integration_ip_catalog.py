"""Integration tests for Integration Platform Connector Catalog API routes in Unified API.

Tests listing catalog applications, category/search filtering, and dynamic spec retrieval.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_list_catalog_apps(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps")
    assert response.status_code == 200, response.text
    apps = response.json()
    assert len(apps) >= 6

    app_ids = [a["app_id"] for a in apps]
    assert "salesforce" in app_ids
    assert "hubspot" in app_ids
    assert "stripe" in app_ids
    assert "servicenow" in app_ids
    assert "itron_mdm" in app_ids
    assert "sftp" in app_ids

    # Validate structure
    sf = next(a for a in apps if a["app_id"] == "salesforce")
    assert sf["display_name"] == "Salesforce CRM"
    assert sf["category"] == "CRM"
    assert sf["auth_type"] == "OAUTH2"
    assert sf["connector_type"] == "DECLARATIVE_HTTP"


@pytest.mark.asyncio
async def test_filter_catalog_apps_by_category(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps?category=CRM")
    assert response.status_code == 200, response.text
    apps = response.json()
    assert len(apps) >= 2
    for app in apps:
        assert app["category"] == "CRM"


@pytest.mark.asyncio
async def test_filter_catalog_apps_by_search(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps?search=stripe")
    assert response.status_code == 200, response.text
    apps = response.json()
    assert len(apps) == 1
    assert apps[0]["app_id"] == "stripe"
    assert apps[0]["category"] == "BILLING"


@pytest.mark.asyncio
async def test_get_declarative_app_spec(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps/salesforce/spec")
    assert response.status_code == 200, response.text
    spec = response.json()
    assert spec["app_id"] == "salesforce"
    assert spec["display_name"] == "Salesforce CRM"
    assert spec["auth_type"] == "OAUTH2"
    assert len(spec["properties"]) > 0

    prop_names = [p["name"] for p in spec["properties"]]
    assert "instance_url" in prop_names
    assert "environment" in prop_names


@pytest.mark.asyncio
async def test_get_native_app_spec(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps/sftp/spec")
    assert response.status_code == 200, response.text
    spec = response.json()
    assert spec["app_id"] == "sftp"
    assert spec["display_name"] == "SFTP File Gateway"
    assert len(spec["properties"]) > 0

    prop_names = [p["name"] for p in spec["properties"]]
    assert "host" in prop_names
    assert "port" in prop_names
    assert "username" in prop_names


@pytest.mark.asyncio
async def test_get_unknown_app_spec_returns_404(auth_client: httpx.AsyncClient) -> None:
    response = await auth_client.get("/api/v1/ip/catalog/apps/non_existent_app_xyz/spec")
    assert response.status_code == 404, response.text
    assert "Connector 'non_existent_app_xyz' not found" in response.json()["detail"]
