import base64
import json
import os
import urllib.error
import urllib.request

import structlog
from dotenv import load_dotenv

# Initialize structured logger
logger = structlog.get_logger()

# Load environment variables from the root .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))

OPENOBSERVE_URL = os.environ.get("OPENOBSERVE_URL", "http://localhost:5080")
OPENOBSERVE_USER = os.environ.get("OPENOBSERVE_USER")
OPENOBSERVE_PASSWORD = os.environ.get("OPENOBSERVE_PASSWORD")

if not OPENOBSERVE_USER or not OPENOBSERVE_PASSWORD:
    raise ValueError("Missing OPENOBSERVE_USER or OPENOBSERVE_PASSWORD in .env")

CREDENTIALS = f"{OPENOBSERVE_USER}:{OPENOBSERVE_PASSWORD}"
ENCODED_CREDENTIALS = base64.b64encode(CREDENTIALS.encode("utf-8")).decode("utf-8")

HEADERS = {"Authorization": f"Basic {ENCODED_CREDENTIALS}", "Content-Type": "application/json"}

ORGANIZATIONS = ["production", "staging", "local_dev"]


def create_organization(name: str) -> None:
    url = f"{OPENOBSERVE_URL}/api/organizations"
    data = json.dumps({"name": name}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")  # noqa: S310

    bound_logger = logger.bind(organization_name=name)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310
            res_body = response.read().decode("utf-8")
            bound_logger.info("organization_provisioned_successfully", response=res_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        if e.code == 409 or (e.code == 400 and "already exists" in error_body.lower()):
            bound_logger.info("organization_already_exists", http_status=e.code)
        else:
            bound_logger.exception(
                "organization_provisioning_failed",
                http_status=e.code,
                reason=error_body,
            )
            raise
    except Exception:
        bound_logger.exception("organization_provisioning_connection_error")
        raise


if __name__ == "__main__":
    logger.info("provisioning_openobserve_organizations_started")
    for org in ORGANIZATIONS:
        create_organization(org)
    logger.info("provisioning_openobserve_organizations_completed")
