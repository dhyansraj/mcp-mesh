# MCP Mesh CLI Tools - Downloads from releases and PyPI
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM python:3.11-slim

ARG TARGETPLATFORM
ARG VERSION

# Install system dependencies
# hadolint ignore=DL3008,DL3015
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r -g 999 mcp-mesh \
    && useradd -r -u 999 -g mcp-mesh mcp-mesh

# Install both meshctl and registry using install.sh script
# hadolint ignore=DL4006
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing meshctl and registry ${VERSION} using install.sh..." && \
    curl -sSL "https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh" | bash -s -- --all --version ${VERSION} --install-dir /usr/local/bin

# The dependency lock (#1454) — same reproducibility argument as the python
# runtime image; see packaging/docker/python-runtime.Dockerfile for the full
# note. A constraints file adds nothing to the image, it only fixes which
# version pip may choose for what the published metadata already requires.
COPY src/runtime/python/constraints.txt /etc/mcp-mesh/constraints.txt

# Install mcp-mesh package from PyPI (remove 'v' prefix if present)
RUN VERSION_NO_V="${VERSION#v}" && \
    echo "Installing mcp-mesh==${VERSION_NO_V} from PyPI against the locked set" && \
    pip install --no-cache-dir -c /etc/mcp-mesh/constraints.txt "mcp-mesh==${VERSION_NO_V}"

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
