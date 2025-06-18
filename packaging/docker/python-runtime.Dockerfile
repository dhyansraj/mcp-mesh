# Multi-stage build for MCP Mesh Python Runtime
# Supports linux/amd64, linux/arm64, linux/arm/v7

FROM --platform=$BUILDPLATFORM python:3.11-slim AS builder

ARG TARGETPLATFORM
ARG BUILDPLATFORM

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy Python runtime source
COPY src/runtime/python/ ./

# Copy and fix pyproject.toml paths
COPY packaging/pypi/pyproject.toml ./
RUN sed -i 's|src/runtime/python/src/mcp_mesh|src/mcp_mesh|g' pyproject.toml && \
    sed -i 's|src/runtime/python/README.md|README.md|g' pyproject.toml && \
    sed -i 's|src/runtime/python/LICENSE|LICENSE|g' pyproject.toml

# Install build dependencies and build wheel
RUN pip install --no-cache-dir build wheel
RUN python -m build --wheel

# Final stage - runtime image
FROM --platform=$TARGETPLATFORM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcp-mesh \
    && useradd -r -g mcp-mesh mcp-mesh

# Copy and install wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl

# Create app directory
RUN mkdir -p /app && chown mcp-mesh:mcp-mesh /app

# Switch to non-root user
USER mcp-mesh
WORKDIR /app

# Health check endpoint (agents will override)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=2)" || exit 1

EXPOSE 8080

# Default entrypoint - agents will override with their scripts
ENTRYPOINT ["python"]
