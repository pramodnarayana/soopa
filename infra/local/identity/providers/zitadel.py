"""Local Zitadel Identity Provider bootstrap plugin.

Loaded dynamically by `infra/local/identity/bootstrap.py` when
`IDENTITY_PROVIDER=zitadel` is configured in `.env`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def bootstrap(*, root_dir: Path, reset: bool) -> dict[str, str]:
    """Delegate local Zitadel bootstrap or idempotent sync to `infra/local/zitadel/`."""
    script_name = "bootstrap.py" if reset else "sync.py"
    target_script = root_dir / "infra" / "local" / "zitadel" / script_name
    if not target_script.exists():
        raise FileNotFoundError(f"Zitadel local script not found: {target_script}")

    logger.info("zitadel_local_plugin_dispatch", script=str(target_script), reset=reset)
    subprocess.run(  # noqa: S603 - Trusted local Python interpreter invoking repo-owned Zitadel script
        [sys.executable, str(target_script)],
        cwd=root_dir,
        check=True,
    )
    return {"IDENTITY_PROVIDER": "zitadel"}


__all__ = ["bootstrap"]
