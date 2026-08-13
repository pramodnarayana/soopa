import sys

import structlog

logger = structlog.get_logger(__name__)

if __name__ == "__main__":
    logger.error(
        "CRITICAL ARCHITECTURE VIOLATION: The Notification Engine is no longer a standalone "
        "web server. It has been integrated into the Unified API Gateway to enforce proper "
        "tenant authentication and context resolution.\n\n"
        "To run the API, start the unified_api application instead.\n"
        "To run the background workers, execute:\n"
        "  python -m notification.workers.sweeper\n"
        "  python -m notification.workers.consumer"
    )
    sys.exit(1)
