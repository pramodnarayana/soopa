#!/usr/bin/env python3
"""
Print local environment developer credentials.
Usage: pnpm credentials
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")

PLATFORM_ADMIN_EMAIL = os.getenv("IDENTITY_PLATFORM_ADMIN_EMAIL", "admin@flowwolf.io")
PLATFORM_ADMIN_PASSWORD = os.getenv("IDENTITY_PLATFORM_ADMIN_PASSWORD", "Password1!")
TENANT_DEFAULT_PASSWORD = os.getenv("IDENTITY_DEFAULT_USER_PASSWORD", "Password1!")
ZITADEL_ADMIN_USER = "zitadel-admin@zitadel.ucp.localhost"
ZITADEL_ADMIN_PASSWORD = "Password1!"  # noqa: S105 - Standard local dev credential display


def main() -> None:
    output = (
        "\n"
        + "=" * 68
        + "\n"
        + "           FLOWWOLF LOCAL DEVELOPER CREDENTIALS\n"
        + "=" * 68
        + "\n"
        + " 1. Flowwolf Dashboard:\n"
        + "    - URL:                     http://localhost:5173\n"
        + f"    - Platform Admin Username: {PLATFORM_ADMIN_EMAIL}\n"
        + f"    - Platform Admin Password: {PLATFORM_ADMIN_PASSWORD}\n"
        + f"    - Tenant Default Password: {TENANT_DEFAULT_PASSWORD} (Assigned to all new tenant users)\n"
        + "    - Role:                    PlatformAdmin (Global Sentinel Tenant)\n"
        + "-" * 68
        + "\n"
        + " 2. Zitadel IAM Console:\n"
        + "    - URL:      http://ucp.localhost:8080/ui/console\n"
        + f"    - Username: {ZITADEL_ADMIN_USER}\n"
        + f"    - Password: {ZITADEL_ADMIN_PASSWORD}\n"
        + "    - Role:     IAM Owner / Instance SuperAdmin\n"
        + "-" * 68
        + "\n"
        + " 3. Mock External Partners:\n"
        + "    - OpenAS2 Server: http://localhost:10080/ (Docker: http://openas2:10080/)\n"
        + "    - SFTP Server:    localhost:2222 (User: testuser, Password: password)\n"
        + "=" * 68
        + "\n\n"
    )
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
