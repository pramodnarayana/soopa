import os
import subprocess
import sys
import time

import requests


def test_api_starts_and_serves_health_without_sqs_vars():
    """
    [Local Dev Parity] Process Topology Smoke Test

    This test proves that the unified-api container can successfully boot and serve
    traffic using ONLY the environment variables actually injected into the ECS task.

    Historically, the local monolithic `.env` file masked process topology bugs
    (like `get_settings()` requiring SQS queues in the API container). Because the
    local `.env` had every variable, it passed locally but crashed in ECS.

    We use `subprocess` to guarantee a clean environment unpolluted by Pytest's
    own imports or the developer's monolithic `.env`.
    """
    # 1. Start with an explicit allowlist of safe system variables, ignoring inherited .env
    allowed_keys = {"PATH", "PYTHONPATH", "LANG", "LC_ALL", "PYTEST_CURRENT_TEST"}
    env = {k: v for k, v in os.environ.items() if k in allowed_keys}

    # 2. Inject ONLY the strict subset required by the unified-api process
    env["DATABASE_URL"] = "postgresql+asyncpg://postgres:password@localhost/test"
    env["IDENTITY_DEFAULT_USER_PASSWORD"] = "dummy_password"  # noqa: S105 - Dummy password for integration test isolation
    env["PUBLIC_BASE_URL"] = "http://localhost:8000"
    env["CORS_ALLOWED_ORIGINS"] = '["http://localhost:3000"]'
    env["AS2_RECEIVE_URL"] = "http://localhost:8000/as2/inbox"

    # Optional OTel suppression to keep logs clean during test
    env["OTEL_ENABLED"] = "false"

    # 3. Boot the server in an isolated process
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "unified_api.main:app", "--port", "8085"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    healthy = False
    try:
        # 4. Wait for uvicorn to boot (simulate the ALB health check)
        max_retries = 20
        for _ in range(max_retries):
            try:
                if process.poll() is not None:
                    break
                resp = requests.get("http://localhost:8085/health", timeout=1)
                # Catch the exact Starlette route ordering bug we fixed
                if resp.status_code == 200:
                    healthy = True
                    break
            except requests.RequestException:
                time.sleep(0.5)

        assert healthy, "API failed to start or /health returned a 404/500."
    finally:
        # 5. Cleanup
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

        if not healthy:
            _stdout_out, _stderr_out = process.communicate()
