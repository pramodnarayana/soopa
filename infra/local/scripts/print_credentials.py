#!/usr/bin/env python3
"""
Print local environment developer credentials.
Usage: pnpm credentials
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

COMPANY_DOMAIN = os.getenv("COMPANY_DOMAIN", "flowwolf.io")
PLATFORM_ADMIN_EMAIL = os.getenv("IDENTITY_PLATFORM_ADMIN_EMAIL", f"admin@{COMPANY_DOMAIN}")
TENANT_DEFAULT_PASSWORD = os.getenv("IDENTITY_DEFAULT_USER_PASSWORD", "Password1!")
PLATFORM_ADMIN_PASSWORD = os.getenv("IDENTITY_PLATFORM_ADMIN_PASSWORD", TENANT_DEFAULT_PASSWORD)
CASDOOR_ADMIN_USER = "admin"
CASDOOR_ADMIN_PASSWORD = os.getenv("CASDOOR_ADMIN_PASSWORD", "Password1!")


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
        + f"    - Platform Admin Email:    {PLATFORM_ADMIN_EMAIL} (Realm: soopa-platform)\n"
        + f"    - Platform Admin Password: {PLATFORM_ADMIN_PASSWORD}\n"
        + f"    - Demo SMB User:           demo@acme.local / {TENANT_DEFAULT_PASSWORD} (Realm: soopa-global)\n"
        + f"    - Demo Individual User:    solo@example.com / {TENANT_DEFAULT_PASSWORD} (Realm: soopa-global)\n"
        + "    - Role:                    PlatformAdmin (Global Sentinel Tenant)\n"
        + "-" * 68
        + "\n"
        + " 2. Casdoor IAM Console:\n"
        + "    - URL:      http://localhost:8080\n"
        + f"    - Username: {CASDOOR_ADMIN_USER} (Org: built-in)\n"
        + f"    - Password: {CASDOOR_ADMIN_PASSWORD}\n"
        + "    - Role:     Casdoor Global Administrator\n"
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
