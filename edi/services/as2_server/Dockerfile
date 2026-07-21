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

# Copy only the dependency manifests first to leverage Docker layer caching
COPY soopaedi/libs/config/pyproject.toml ./libs/config/pyproject.toml
COPY soopaedi/libs/database/pyproject.toml ./libs/database/pyproject.toml
COPY soopaedi/libs/identity/pyproject.toml ./libs/identity/pyproject.toml
COPY soopaedi/libs/as2_core/pyproject.toml ./libs/as2_core/pyproject.toml
COPY soopaedi/libs/observability/pyproject.toml ./libs/observability/pyproject.toml
COPY soopaedi/services/as2_server/pyproject.toml ./services/as2_server/pyproject.toml

# Copy source code
COPY soopaedi/libs/ ./libs/
COPY soopaedi/services/as2_server/ ./services/as2_server/

# Install all dependencies into /install for the final stage
RUN uv pip install --system --no-cache \
    ./libs/config \
    ./libs/database \
    ./libs/identity \
    ./libs/as2_core \
    ./libs/observability \
    ./services/as2_server

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN useradd --create-home --shell /bin/bash soopaedi
USER soopaedi
WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY --from=builder /build/libs/ ./libs/
COPY --from=builder /build/services/as2_server/ ./services/as2_server/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# gunicorn manages worker lifecycle; uvicorn workers handle async requests.
# 2 workers per CPU core is the standard recommendation.
CMD ["gunicorn", "as2_server.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
