# =============================================================================
# Soopa Platform Monolith — Production Dockerfile
# Multi-stage build for minimal image size.
# Contains all EDI, UCP, and Platform components.
# Run with different entrypoints to boot specific services.
# =============================================================================

# --- Stage 1: Builder ---
FROM python:3.13-slim-bookworm AS builder

# /build is the conventional builder WORKDIR — separate from /app (runtime).
# We use --relocatable so the .venv can be safely copied to any path
# without breaking the absolute shebangs uv embeds in scripts.
WORKDIR /build

# Install build dependencies for C extensions (like pykcs11)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.9 \
    swig=4.1.0-0.2 \
    pkg-config=1.8.1-1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.11.15

# Copy the entire workspace (uv requires the full tree for workspace resolution)
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY core ./core

# Create a relocatable virtual environment separately, as uv sync no longer supports the flag directly.
# --no-editable prevents workspace packages from referencing /build paths so they work in /app.
RUN uv venv --relocatable .venv && uv sync --no-dev --frozen --all-packages --no-editable
# --- Stage 2: Production Runtime ---
FROM python:3.13-slim-bookworm AS runtime

# Security: run as non-root
RUN useradd --create-home --shell /bin/bash --uid 1000 soopa
USER 1000
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
