# =============================================================================
# Soopaedi AS2 Server — Production Dockerfile
# Multi-stage build for minimal image size.
# Runs as a non-root user using gunicorn + uvicorn workers.
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy workspace root files for uv workspace resolution
COPY pyproject.toml uv.lock* ./

# Copy only the dependency manifests first to leverage Docker layer caching
COPY apps/edi/packages/config/pyproject.toml ./apps/edi/packages/config/pyproject.toml
COPY apps/edi/packages/database/pyproject.toml ./apps/edi/packages/database/pyproject.toml
COPY apps/edi/packages/security/pyproject.toml ./apps/edi/packages/security/pyproject.toml
COPY apps/edi/packages/as2_core/pyproject.toml ./apps/edi/packages/as2_core/pyproject.toml
COPY core/platform/packages/observability/python/pyproject.toml ./core/platform/packages/observability/python/pyproject.toml
COPY apps/edi/apps/edi-as2-server/pyproject.toml ./apps/edi/apps/edi-as2-server/pyproject.toml

# Copy source code
COPY apps/edi/packages/config/ ./apps/edi/packages/config/
COPY apps/edi/packages/database/ ./apps/edi/packages/database/
COPY apps/edi/packages/security/ ./apps/edi/packages/security/
COPY apps/edi/packages/as2_core/ ./apps/edi/packages/as2_core/
COPY core/platform/packages/observability/python/ ./core/platform/packages/observability/python/
COPY apps/edi/apps/edi-as2-server/ ./apps/edi/apps/edi-as2-server/

# Install dependencies using uv workspaces
RUN uv pip install --system --no-cache ./apps/edi/apps/edi-as2-server

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN useradd --create-home --shell /bin/bash soopaedi
USER soopaedi
WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source exactly as it was built
COPY --from=builder /build/apps/ /app/apps/
COPY --from=builder /build/core/ /app/core/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH="/app/apps/edi/apps/edi-as2-server/src:/app/apps/edi/packages/as2_core/src:/app/apps/edi/packages/config/src:/app/apps/edi/packages/database/src:/app/apps/edi/packages/security/src:/app/core/platform/packages/observability/python/src"

EXPOSE 8000

# gunicorn manages worker lifecycle; uvicorn workers handle async requests.
# 2 workers per CPU core is the standard recommendation.
CMD ["gunicorn", "as2_server.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
