"""Narrow HTTP integration tests for AwsSecretsManagerAdapter against an in-process Secrets Manager HTTP server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from werkzeug.wrappers import Request, Response

pytestmark = pytest.mark.integration


def _register_secrets_manager_http_handler(httpserver: HTTPServer) -> dict[str, str]:
    """Registers a stateful AWS Secrets Manager JSON-RPC 1.1 handler on the local HTTP server."""
    vault_state: dict[str, str] = {}

    def _handle(request: Request) -> Response:
        target = request.headers.get("X-Amz-Target", "")
        body = json.loads(request.get_data(as_text=True) or "{}")

        if target.endswith(".CreateSecret"):
            name = str(body["Name"])
            vault_state[name] = str(body["SecretString"])
            return Response(
                json.dumps(
                    {
                        "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{name}",
                        "Name": name,
                    }
                ),
                status=200,
                content_type="application/x-amz-json-1.1",
            )

        if target.endswith(".GetSecretValue"):
            secret_id = str(body["SecretId"])
            if secret_id not in vault_state:
                return Response(
                    json.dumps(
                        {
                            "__type": "ResourceNotFoundException",
                            "message": f"Secrets Manager can't find the specified secret: {secret_id}",
                        }
                    ),
                    status=400,
                    content_type="application/x-amz-json-1.1",
                )
            return Response(
                json.dumps({"Name": secret_id, "SecretString": vault_state[secret_id]}),
                status=200,
                content_type="application/x-amz-json-1.1",
            )

        if target.endswith(".DeleteSecret"):
            secret_id = str(body["SecretId"])
            vault_state.pop(secret_id, None)
            return Response(
                json.dumps(
                    {
                        "ARN": f"arn:aws:secretsmanager:us-east-1:000000000000:secret:{secret_id}",
                        "Name": secret_id,
                    }
                ),
                status=200,
                content_type="application/x-amz-json-1.1",
            )

        return Response(
            json.dumps(
                {"__type": "InvalidRequestException", "message": f"Unsupported target: {target}"}
            ),
            status=400,
            content_type="application/x-amz-json-1.1",
        )

    httpserver.expect_request("/", method="POST").respond_with_handler(_handle)
    return vault_state


def _build_test_adapter(
    *,
    endpoint_url: str,
    secrets_mount_path: str,
    path_resolver: MountedSecretPathResolver | None = None,
) -> AwsSecretsManagerAdapter:
    return AwsSecretsManagerAdapter(
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        secrets_prefix="",
        secrets_mount_path=secrets_mount_path,
        path_resolver=path_resolver,
    )


@pytest.fixture
def temp_secrets_dir(tmp_path: Path) -> str:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    return str(secrets_dir)


@pytest.mark.asyncio
async def test_aws_secrets_manager_integration(
    httpserver: HTTPServer,
    temp_secrets_dir: str,
) -> None:
    _register_secrets_manager_http_handler(httpserver)
    adapter = _build_test_adapter(
        endpoint_url=httpserver.url_for("/"),
        secrets_mount_path=temp_secrets_dir,
    )

    test_key_data = b"INTEGRATION_TEST_KEY_DATA"
    category = "test_category"

    ref = await adapter.store_private_key(test_key_data, category=category)
    assert ref.startswith(f"{category}/")

    retrieved_data = await adapter.retrieve_secret(ref)
    assert retrieved_data == test_key_data

    secret_str = await adapter.get_secret(ref)
    assert secret_str == "INTEGRATION_TEST_KEY_DATA"

    await adapter.delete_secret(ref)

    with pytest.raises(ValueError, match="Secret not found"):
        await adapter.retrieve_secret(ref)


@pytest.mark.asyncio
async def test_aws_secrets_manager_integration_with_mounted_file(
    httpserver: HTTPServer,
    temp_secrets_dir: str,
) -> None:
    _register_secrets_manager_http_handler(httpserver)
    adapter = _build_test_adapter(
        endpoint_url=httpserver.url_for("/"),
        secrets_mount_path=temp_secrets_dir,
        path_resolver=MountedSecretPathResolver(),
    )
    category = "sidecar_cat"
    test_data = b"INTEGRATION_SIDECAR_DATA"
    mounted_distinct_data = b"MOUNTED_DISTINCT_FILE_DATA"

    ref = await adapter.store_private_key(test_data, category=category)
    secret_id = ref.split("/")[-1]

    mounted_file = Path(temp_secrets_dir) / category / secret_id
    mounted_file.parent.mkdir(parents=True, exist_ok=True)
    mounted_file.write_bytes(mounted_distinct_data)

    assert mounted_file.is_file()

    retrieved = await adapter.retrieve_secret(ref)
    assert retrieved == mounted_distinct_data

    await adapter.delete_secret(ref)
    assert not mounted_file.exists()

    with pytest.raises(ValueError, match="Secret not found"):
        await adapter.retrieve_secret(ref)
