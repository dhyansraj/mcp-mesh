# Multi-stage Docker build for Data Processor Agent
# This demonstrates production-ready containerization of complex MCP Mesh agents

# Stage 1: Build stage with all development dependencies
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /build

# Install system dependencies needed for building
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy package configuration files
COPY pyproject.toml README.md ./

# Copy source code
COPY data_processor_agent/ ./data_processor_agent/

# Install build dependencies and build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# Stage 2: Runtime stage with minimal dependencies
FROM python:3.11-slim AS runtime

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd -r mcpmesh && useradd -r -g mcpmesh mcpmesh

# Set working directory
WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    # Required for some Python packages
    libc6-dev \
    # Network utilities for health checks
    curl \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Copy built wheel from builder stage
COPY --from=builder /build/dist/*.whl /tmp/

# Install the application and its dependencies
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl

# Create directories for data and cache
RUN mkdir -p /app/data /app/cache /app/logs && \
    chown -R mcpmesh:mcpmesh /app

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER mcpmesh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${HTTP_PORT:-9090}/health || exit 1

# Expose the agent port
EXPOSE 9090

# Set default environment variables
ENV AGENT_NAME=data-processor \
    HTTP_PORT=9090 \
    LOG_LEVEL=INFO \
    CACHE_ENABLED=true \
    METRICS_ENABLED=true \
    TEMP_DIR=/app/cache

# Use entrypoint script for flexibility
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command
CMD ["data-processor-agent"]