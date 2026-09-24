"""
Syncs Zitadel Terraform outputs to the root .env file.

Mapping: ENV_VAR_NAME -> terraform_output_key
Each entry declares which Terraform output becomes which .env variable.
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
    "ZITADEL_PLATFORM_ORG_ID": "platform_org_id",
    "ZITADEL_UCP_PROJECT_ID": "ucp_project_id",
    "ZITADEL_EDI_PROJECT_ID": "edi_project_id",
    "ZITADEL_UCP_WEB_CLIENT_ID": "ucp_web_client_id",
    "ZITADEL_UCP_API_CLIENT_ID": "ucp_api_client_id",
    "ZITADEL_EDI_API_CLIENT_ID": "edi_api_client_id",
    "ZITADEL_MACHINE_KEY": "iam_manager_sa_key",
    "ZITADEL_PLATFORM_ADMIN_ID": "platform_admin_id",
}


def _read_terraform_outputs(script_dir: Path) -> dict[str, str]:
    """
    Run `terraform output -json` and return a flat mapping of output_name -> value.

    Raises:
        subprocess.CalledProcessError: if terraform exits non-zero.
        json.JSONDecodeError: if the output is not valid JSON.
    """
    terraform_bin = shutil.which("terraform")
    if not terraform_bin:
        raise RuntimeError("terraform binary not found in PATH")

    result = subprocess.run(  # noqa: S603
        [terraform_bin, "output", "-json"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    tf_output: dict = json.loads(result.stdout)
    return {key: str(entry.get("value", "")) for key, entry in tf_output.items()}


def _sanitize_env_value(value: str) -> str:
    """
    Ensure the value is safe to write on a single line in a .env file.
    Escapes actual newline (LF) and carriage return (CR) characters to their
    two-character literal representations so parsers do not break mid-line.
    """
    safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
    safe_value = safe_value.replace("\r", "").replace("\n", "\\n")
    return safe_value


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
                lines[i] = f'{key}="{safe_value}"\n'
                updated_keys.add(key)
                logger.info("Updated key", key=key)
                break

    # Pass 2: append keys that are not yet present in the file
    for key, value in updates.items():
        if key not in updated_keys:
            safe_value = _sanitize_env_value(value)
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f'{key}="{safe_value}"\n')
            logger.info("Added key", key=key)

    env_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    script_dir = Path(__file__).parent.resolve()
    root_dir = script_dir.parent.parent.parent
    env_path = root_dir / ".env"

    logger.info("Syncing Zitadel Terraform outputs to .env...")

    if not env_path.exists():
        logger.error(
            "ERROR: .env not found",
            env_path=str(env_path),
            remedy="Run `cp .env.example .env` before running this script.",
        )
        sys.exit(1)

    try:
        tf_outputs = _read_terraform_outputs(script_dir)
    except subprocess.CalledProcessError as e:
        logger.exception(
            "ERROR: 'terraform output' failed",
            exit_code=e.returncode,
            remedy="Ensure Terraform has been initialized (`terraform init`) and applied.",
        )
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.exception("ERROR: Failed to parse terraform output as JSON", error=str(e))
        sys.exit(1)

    # Build the updates dict, warning for any missing Terraform outputs
    updates: dict[str, str] = {}
    for env_var, tf_key in _TERRAFORM_TO_ENV_MAPPINGS.items():
        value = tf_outputs.get(tf_key, "")
        if not value:
            logger.warning(
                "WARNING: Terraform output not found or empty — skipping",
                tf_key=tf_key,
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
