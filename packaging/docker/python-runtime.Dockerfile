# MCP Mesh Python Runtime - Installs from PyPI
# Supports linux/amd64, linux/arm64, linux/arm/v7

FROM --platform=$TARGETPLATFORM python:3.11-slim

ARG VERSION

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcp-mesh \
    && useradd -r -g mcp-mesh mcp-mesh

# Install mcp-mesh package from PyPI
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing mcp-mesh==${VERSION} from PyPI" && \
    pip install --no-cache-dir mcp-mesh==${VERSION}

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
