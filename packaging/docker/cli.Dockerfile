# MCP Mesh CLI Tools - Downloads from releases and PyPI
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM python:3.11-slim

ARG TARGETPLATFORM
ARG VERSION

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcp-mesh \
    && useradd -r -g mcp-mesh mcp-mesh

# Install both meshctl and registry using install.sh script
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing meshctl and registry ${VERSION} using install.sh..." && \
    curl -sSL "https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh" | bash -s -- --all --version ${VERSION} --install-dir /usr/local/bin

# Install mcp-mesh package from PyPI
RUN echo "Installing mcp-mesh==${VERSION} from PyPI" && \
    pip install --no-cache-dir mcp-mesh==${VERSION}

# Create workspace
RUN mkdir -p /workspace && chown mcp-mesh:mcp-mesh /workspace

# Switch to non-root user
USER mcp-mesh
WORKDIR /workspace

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD meshctl version || exit 1

# Default entrypoint
ENTRYPOINT ["/usr/local/bin/meshctl"]
CMD ["--help"]
