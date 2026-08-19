# =============================================================================
# Soopa Platform Monolith — Production Dockerfile
# Multi-stage build for minimal image size.
# Contains all EDI, UCP, and Platform components.
# Run with different entrypoints to boot specific services.
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.13-slim AS builder

# /build is the conventional builder WORKDIR — separate from /app (runtime).
# We use --relocatable so the .venv can be safely copied to any path
# without breaking the absolute shebangs uv embeds in scripts.
WORKDIR /build

# Install build dependencies for C extensions (like pykcs11)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    swig \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy the entire workspace (uv requires the full tree for workspace resolution)
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY core ./core

# --relocatable: rewrites venv shebangs to use relative paths so the .venv
# directory is portable and works correctly when copied to /app in the runtime stage.
RUN uv sync --no-dev --frozen --all-packages --relocatable

# --- Stage 2: Production Runtime ---
FROM python:3.13-slim AS runtime

# Security: run as non-root
RUN useradd --create-home --shell /bin/bash soopa
USER soopa
WORKDIR /app

# Copy the built virtual environment from builder (works because of --relocatable)
COPY --from=builder --chown=soopa:soopa /build/.venv /app/.venv

# Copy application source
COPY --from=builder --chown=soopa:soopa /build/apps /app/apps
COPY --from=builder --chown=soopa:soopa /build/core /app/core

# Ensure python uses the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose standard web port (can be overridden)
EXPOSE 8000

# Default command (Should be overridden in docker-compose or ECS task definition)
CMD ["python", "--version"]
