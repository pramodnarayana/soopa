"""PEP 610 dynamic workspace hot-reload launcher for local ASGI development servers.

Discovers all editable workspace Python packages via PEP 610 (`direct_url.json`) at startup
so Uvicorn watches every installed monorepo bounded context and platform package without
hardcoding domain names or relative paths (Open-Closed Principle).
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import structlog
import uvicorn

logger = structlog.get_logger(__name__)


def parse_editable_package_src_dir(direct_url_json: str) -> Path | None:
    """Extracts the source root Path from a PEP 610 `direct_url.json` payload if editable."""
    try:
        parsed_raw: object = json.loads(direct_url_json)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed_raw, dict):
        return None

    dir_info = parsed_raw.get("dir_info")
    if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
        return None

    raw_url = parsed_raw.get("url")
    if not isinstance(raw_url, str) or not raw_url.startswith("file://"):
        return None

    parsed_url = urlparse(raw_url)
    pkg_root = Path(url2pathname(parsed_url.path)).resolve()
    subdirectory = parsed_raw.get("subdirectory")
    if isinstance(subdirectory, str) and subdirectory.strip():
        candidate_root = (pkg_root / subdirectory.strip()).resolve()
        if not candidate_root.is_relative_to(pkg_root):
            return None
        pkg_root = candidate_root
    src_dir = pkg_root / "src"
    if src_dir.is_dir():
        return src_dir
    if pkg_root.is_dir():
        return pkg_root
    return None


def discover_editable_reload_dirs(direct_url_payloads: Sequence[str]) -> list[str]:
    """Resolves deduplicated, sorted reload directories from PEP 610 `direct_url.json` strings."""
    resolved_dirs: set[str] = set()
    for payload in direct_url_payloads:
        candidate = parse_editable_package_src_dir(payload)
        if candidate is not None:
            resolved_dirs.add(str(candidate))
    return sorted(resolved_dirs)


def collect_installed_editable_reload_dirs() -> list[str]:
    """Reads PEP 610 metadata across installed distributions to discover workspace source roots."""
    payloads: list[str] = []
    for dist in importlib.metadata.distributions():
        raw_direct_url = dist.read_text("direct_url.json")
        if raw_direct_url:
            payloads.append(raw_direct_url)

    discovered = discover_editable_reload_dirs(payloads)
    local_src = (Path.cwd() / "src").resolve()
    if local_src.is_dir() and str(local_src) not in discovered:
        discovered.append(str(local_src))
        discovered.sort()
    return discovered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run local ASGI dev server with workspace-wide PEP 610 hot reload."
    )
    parser.add_argument(
        "--app",
        required=True,
        help="ASGI application import string (e.g. unified_api.main:app)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")  # noqa: S104 - Local dev server intentionally binds all interfaces for container/proxy parity
    parser.add_argument("--port", type=int, default=3000, help="Bind port (default: 3000)")
    args = parser.parse_args()

    reload_dirs = collect_installed_editable_reload_dirs()
    logger.info(
        "local_dev_server_starting",
        app=args.app,
        host=args.host,
        port=args.port,
        watched_package_count=len(reload_dirs),
    )
    uvicorn.run(
        args.app,
        host=args.host,
        port=args.port,
        reload=True,
        reload_dirs=reload_dirs,
    )


if __name__ == "__main__":
    main()
