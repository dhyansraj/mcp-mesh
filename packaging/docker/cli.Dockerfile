# Multi-stage build for MCP Mesh CLI Tools
# Supports linux/amd64, linux/arm64

FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS go-builder

ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETOS
ARG TARGETARCH

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git ca-certificates

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . ./

# Build CLI tools for target architecture
ENV CGO_ENABLED=0
ENV GOOS=$TARGETOS
ENV GOARCH=$TARGETARCH

RUN go build -ldflags="-w -s" -o meshctl ./cmd/meshctl
RUN go build -ldflags="-w -s" -o registry ./cmd/mcp-mesh-registry

# Python stage for runtime tools
FROM --platform=$BUILDPLATFORM python:3.11-slim AS python-builder

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

# Build wheel
RUN pip install --no-cache-dir build wheel
RUN python -m build --wheel

# Final stage - CLI tools image
FROM --platform=$TARGETPLATFORM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcp-mesh \
    && useradd -r -g mcp-mesh mcp-mesh

# Copy Go binaries
COPY --from=go-builder /build/meshctl /usr/local/bin/meshctl
COPY --from=go-builder /build/registry /usr/local/bin/registry

# Copy and install Python wheel
COPY --from=python-builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl

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
