# tsuite-mesh Base Image
# Pre-built image with all MCP Mesh packages for faster test execution
#
# Build args:
#   VERSION - The MCP Mesh version (e.g., 0.8.0-beta.6)
#   PIP_VERSION - The pip version format (e.g., 0.8.0b6)

FROM python:3.11-slim

ARG VERSION
ARG PIP_VERSION

# Validate build args
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    if [ -z "$PIP_VERSION" ]; then echo "PIP_VERSION build arg is required" && exit 1; fi

# Install system dependencies and Node.js 22
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify Node.js installation
RUN node --version && npm --version

# Install MCP Mesh npm packages globally
RUN echo "Installing npm packages @mcpmesh/*@${VERSION}..." && \
    npm install -g @mcpmesh/cli@${VERSION} && \
    npm install -g @mcpmesh/sdk@${VERSION} && \
    npm install -g @mcpmesh/core@${VERSION}

# Verify meshctl installation
RUN meshctl --version

# Install MCP Mesh pip package
RUN echo "Installing pip package mcp-mesh==${PIP_VERSION}..." && \
    pip install --no-cache-dir mcp-mesh==${PIP_VERSION}

# Verify mesh module installation
RUN python -c "import mesh; print('mesh module imported successfully')"

# Install tsuite dependencies for running tests inside container
RUN pip install --no-cache-dir click rich pyyaml jsonpath-ng requests flask docker

# Create mcp-mesh user for security (matching official runtime images)
RUN groupadd -r mcp-mesh && useradd -r -g mcp-mesh mcp-mesh

# Create workspace directory
RUN mkdir -p /workspace && chown mcp-mesh:mcp-mesh /workspace

# Set working directory
WORKDIR /workspace

# Labels for identification
LABEL org.opencontainers.image.title="tsuite-mesh"
LABEL org.opencontainers.image.description="MCP Mesh Test Suite Base Image"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL mcp-mesh.cli.version="${VERSION}"
LABEL mcp-mesh.sdk.version="${VERSION}"
LABEL mcp-mesh.pip.version="${PIP_VERSION}"

# Default command
CMD ["bash"]
