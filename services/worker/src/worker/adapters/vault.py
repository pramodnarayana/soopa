import asyncio
import logging
import os
import sys

import hvac

logger = logging.getLogger(__name__)


class WorkerVaultAdapter:
    def __init__(self) -> None:
        self.url = os.getenv("VAULT_ADDR", "http://localhost:8200")
        token = os.getenv("VAULT_TOKEN")
        env = os.getenv("ENVIRONMENT", "development")
        if not token:
            if env in ("development", "dev", "test", "local") or "pytest" in sys.modules:
                token = "root"
            else:
                raise ValueError("VAULT_TOKEN required in non-dev")

        self.token = token
        self.client = hvac.Client(url=self.url, token=self.token)
        self.mount_point = "secret"

    async def get_secret(self, vault_ref: str) -> str:
        # HVAC is synchronous, but we wrap in asyncio.to_thread for the port
        def _fetch() -> str:
            resp = self.client.secrets.kv.v2.read_secret_version(
                path=vault_ref, mount_point=self.mount_point
            )
            data = resp.get("data", {}).get("data", {})
            val = next(iter(data.values()), None)
            return val if isinstance(val, str) else ""

        return await asyncio.to_thread(_fetch)
