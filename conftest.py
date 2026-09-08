"""
Monorepo Root conftest.py — Single Source of Truth for Test Environment

All test configuration (database URLs, AWS credentials, identity provider URLs)
is loaded from the project's `.env` file here, ONCE, at the start of the entire
test session.

Individual conftest.py files MUST NOT duplicate `os.environ.setdefault` calls
for infrastructure values. They should only define pytest fixtures.

See: .env.example for the full list of required environment variables.
"""

from dotenv import load_dotenv

load_dotenv()
