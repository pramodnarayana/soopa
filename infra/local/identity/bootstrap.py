#!/usr/bin/env python3
"""Provider-agnostic Local Identity Bootstrap Composition Root.

Dispatches `pnpm infra:bootstrap-identity` and `pnpm infra:sync-identity` dynamically to
`infra.local.identity.providers.<IDENTITY_PROVIDER>` (default: `casdoor`).

Adheres strictly to the Open-Closed Principle: adding or switching an Identity Provider
requires ONLY dropping a new module under `infra/local/identity/providers/` implementing
`bootstrap(root_dir: Path, *, reset: bool) -> dict[str, str]` and setting `IDENTITY_PROVIDER`
in `.env` — zero edits to `package.json` or this entrypoint.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = structlog.get_logger(__name__)

DEFAULT_IDENTITY_PROVIDER = "casdoor"
_SAFE_PROVIDER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@runtime_checkable
class LocalIdentityProviderModule(Protocol):
    """Contract every local IdP bootstrap plugin under `providers/` must implement."""

    def bootstrap(self, *, root_dir: Path, reset: bool) -> dict[str, str]: ...


def resolve_provider_name(raw_provider: str | None) -> str:
    """Validate and normalize the configured provider name to prevent arbitrary module loading."""
    normalized = (raw_provider or DEFAULT_IDENTITY_PROVIDER).strip().lower()
    if not _SAFE_PROVIDER_NAME_RE.match(normalized):
        raise ValueError(
            f"Invalid IDENTITY_PROVIDER={normalized!r}. Must match ^[a-z][a-z0-9_]{{0,31}}$."
        )
    return normalized


def load_provider_plugin(provider_name: str) -> LocalIdentityProviderModule:
    """Dynamically load `infra.local.identity.providers.<provider_name>` and verify its contract."""
    module_path = f"infra.local.identity.providers.{provider_name}"
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ValueError(
            f"No local identity bootstrap plugin found for IDENTITY_PROVIDER={provider_name!r} "
            f"(expected module '{module_path}')."
        ) from exc

    if not isinstance(module, LocalIdentityProviderModule):
        raise TypeError(
            f"Plugin '{module_path}' does not implement required "
            "bootstrap(*, root_dir: Path, reset: bool) -> dict[str, str] contract."
        )
    return module


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap or sync the configured local Identity Provider."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset local IdP state/volumes before bootstrapping.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override IDENTITY_PROVIDER from .env (default: casdoor).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    load_dotenv(_REPO_ROOT / ".env")
    provider_name = resolve_provider_name(args.provider or os.getenv("IDENTITY_PROVIDER"))
    plugin = load_provider_plugin(provider_name)
    logger.info("local_identity_bootstrap_dispatch", provider=provider_name, reset=args.reset)
    plugin.bootstrap(root_dir=_REPO_ROOT, reset=args.reset)


if __name__ == "__main__":
    main()
