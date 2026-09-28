import os
import subprocess
import sys
import time

import requests


def test_as2_server_starts_and_serves_health_without_sqs_vars():
    """
    [Local Dev Parity] Process Topology Smoke Test

    This test proves that the AS2 Server container can successfully boot and serve
    traffic using ONLY the environment variables actually injected into its ECS task.

    Historically, apps crashed in ECS because they accidentally imported code that
    evaluated full worker settings (requiring SQS variables) during module load.

    We use `subprocess` to guarantee a clean environment unpolluted by Pytest's
    own imports or the developer's monolithic `.env`.
    """
    # 1. Clean the environment of all "superset" variables
    env = os.environ.copy()
    keys_to_delete = [k for k in env if k.startswith("SQS_")]
    for k in keys_to_delete:
        del env[k]

    # 2. Inject ONLY the strict subset required by the AS2 Server process
    env["DATABASE_URL"] = "postgresql+asyncpg://postgres:password@localhost/test"

    # S3 Vars required by Aioboto3PayloadStorage
    env["S3_BUCKET"] = "dummy-bucket"
    env["S3_REGION"] = "us-east-1"
    env["S3_ENDPOINT_URL"] = "http://localhost:4566"
    env["S3_ACCESS_KEY_ID"] = "dummy"
    env["S3_SECRET_ACCESS_KEY"] = "dummy"

    # Optional OTel suppression to keep logs clean during test
    env["OTEL_ENABLED"] = "false"

    # 3. Boot the server in an isolated process
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "as2_server.main:app", "--port", "8086"],
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
                # AS2 server has a health endpoint registered in its ops router
                resp = requests.get("http://localhost:8086/health", timeout=1)
                if resp.status_code == 200:
                    healthy = True
                    break
            except requests.RequestException:
                time.sleep(0.5)

        assert healthy, "AS2 Server failed to start or /health returned an error."
    finally:
        # 5. Cleanup
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

        if not healthy:
            _stdout_out, _stderr_out = process.communicate()
