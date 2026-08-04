# MCP Mesh Python Runtime - Installs from PyPI
# Supports linux/amd64, linux/arm64, linux/arm/v7

FROM --platform=$TARGETPLATFORM python:3.11-slim

ARG VERSION

# Install runtime dependencies. uid/gid pinned to 999: the helm
# mcp-mesh-agent chart forces runAsUser/runAsGroup/fsGroup 999, which must
# match this user so files chowned to mcp-mesh in-image stay writable.
# hadolint ignore=DL3008,DL3015
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r -g 999 mcp-mesh \
    && useradd -r -u 999 -g mcp-mesh mcp-mesh

# The dependency lock (#1454). Without it this image was not reproducible:
# `pip install mcp-mesh==X.Y.Z` resolves the transitive tree at BUILD time, so
# two builds of one mesh version shipped different trees. That is precisely how
# a FastMCP default-flip enabling DNS-rebinding Host validation reached users in
# #1312 — no mesh change, no release, 421 on every k8s Service-DNS /mcp call.
#
# It is a constraints file, not a requirements file: it does not add anything to
# the image. `pip install mcp-mesh` still installs exactly what the published
# metadata asks for (litellm stays out — #1383); the file only fixes WHICH
# version of each of those pip may choose. That is also why one file serves both
# linux/amd64 and linux/arm64: the two arches resolve to the identical set, and
# any entry that did not apply would simply be unused.
COPY src/runtime/python/constraints.txt /etc/mcp-mesh/constraints.txt

# Install mcp-mesh package from PyPI, pinned to the locked tree
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing mcp-mesh==${VERSION} from PyPI against the locked set" && \
    pip install --no-cache-dir -c /etc/mcp-mesh/constraints.txt mcp-mesh==${VERSION}

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
