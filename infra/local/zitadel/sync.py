"""
Syncs Zitadel Pulumi outputs to the root .env file.

Mapping: ENV_VAR_NAME -> pulumi_output_key
Each entry declares which Pulumi output becomes which .env variable.
"""

import json
import shutil
import subprocess
import sys

import structlog

logger = structlog.get_logger(__name__)
from pathlib import Path

# ── Schema: .env variable name → Terraform output key ─────────────────────────
_TERRAFORM_TO_ENV_MAPPINGS: dict[str, str] = {
    "IDENTITY_PLATFORM_ORG_ID": "platform_org_id",
    "IDENTITY_UCP_PROJECT_ID": "ucp_project_id",
    "IDENTITY_EDI_PROJECT_ID": "edi_project_id",
    "IDENTITY_UCP_WEB_CLIENT_ID": "ucp_web_client_id",
    "IDENTITY_UCP_API_CLIENT_ID": "ucp_api_client_id",
    "IDENTITY_EDI_API_CLIENT_ID": "edi_api_client_id",
    "IDENTITY_MACHINE_KEY": "iam_manager_sa_key",
    "IDENTITY_PLATFORM_ADMIN_ID": "platform_admin_id",
}


def _read_pulumi_outputs(script_dir: Path) -> dict[str, str]:
    """
    Run `pulumi stack output --json` and return a flat mapping of output_name -> value.

    Raises:
        subprocess.CalledProcessError: if pulumi exits non-zero.
        json.JSONDecodeError: if the output is not valid JSON.
    """
    pulumi_bin = shutil.which("pulumi")
    if not pulumi_bin:
        raise RuntimeError("pulumi binary not found in PATH")

    pulumi_dir = script_dir.parent / "zitadel_pulumi"

    result = subprocess.run(  # noqa: S603
        [pulumi_bin, "stack", "output", "--json", "--show-secrets"],
        cwd=pulumi_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    pulumi_output: dict = json.loads(result.stdout)
    return {key: str(value) for key, value in pulumi_output.items()}


def _sanitize_env_value(value: str) -> str:
    """
    Ensure the value is safe to write on a single line in a .env file.
    If the value looks like a JSON object, wrap it in single quotes to
    prevent standard dotenv parsers from misinterpreting internal quotes or backslashes.
    """
    if value.startswith("{") and value.endswith("}"):
        # It's a JSON string. Do not wrap in quotes and do not escape.
        # This perfectly matches the .env.example format.
        return value

    safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
    safe_value = safe_value.replace("\r", "").replace("\n", "\\n")
    return f'"{safe_value}"'


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """
    Write key=value pairs into an existing .env file.

    - Existing keys are updated in-place, preserving line order and comments.
    - Keys not yet present are appended to the end.
    - All values are sanitized to single-line safe strings before writing.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_keys: set[str] = set()

    # Pass 1: update keys that already exist in the file
    for i, line in enumerate(lines):
        for key in updates:
            if line.startswith(f"{key}="):
                safe_value = _sanitize_env_value(updates[key])
                lines[i] = f"{key}={safe_value}\n"
                updated_keys.add(key)
                logger.info("Updated key", key=key)
                break

    # Pass 2: append keys that are not yet present in the file
    for key, value in updates.items():
        if key not in updated_keys:
            safe_value = _sanitize_env_value(value)
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{key}={safe_value}\n")
            logger.info("Added key", key=key)

    env_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent.parent.parent
    env_path = root_dir / ".env"

    logger.info("Syncing Zitadel Pulumi outputs to .env...")

    if not env_path.exists():
        logger.error(
            "ERROR: .env not found",
            env_path=str(env_path),
            remedy="Run `cp .env.example .env` before running this script.",
        )
        sys.exit(1)

    try:
        outputs = _read_pulumi_outputs(script_dir)
    except subprocess.CalledProcessError as e:
        logger.exception(
            "ERROR: 'pulumi stack output' failed",
            exit_code=e.returncode,
            remedy="Ensure Pulumi has been applied (`pulumi up`).",
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.exception("ERROR: Failed to parse pulumi output as JSON", error=str(e))
        sys.exit(1)

    # Build the updates dict, warning for any missing Pulumi outputs
    updates: dict[str, str] = {}
    for env_var, pulumi_key in _TERRAFORM_TO_ENV_MAPPINGS.items():
        value = outputs.get(pulumi_key, "")
        if not value:
            logger.warning(
                "WARNING: Pulumi output not found or empty — skipping",
                pulumi_key=pulumi_key,
                env_var=env_var,
            )
            continue
        updates[env_var] = value

    _update_env_file(env_path, updates)
    logger.info("✅ Successfully synchronized Zitadel outputs to .env")


if __name__ == "__main__":
    try:
        main()
    except OSError:
        logger.exception("File I/O error")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.exception("\nSync cancelled.")
        sys.exit(0)
