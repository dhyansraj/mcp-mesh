# MCP Mesh UI Server - Downloads pre-built binary from GitHub releases
# Default basePath: /ops/dashboard (for Kubernetes deployments)
#
# Override basePath: use packaging/docker/ui-custom.Dockerfile
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM debian:12-slim

ARG TARGETPLATFORM
ARG VERSION

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    tzdata \
    wget \
    && groupadd -g 1001 mcp-mesh \
    && useradd -u 1001 -g mcp-mesh mcp-mesh \
    && rm -rf /var/lib/apt/lists/*

# Download and extract dashboard UI binary based on platform
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    case "$TARGETPLATFORM" in \
        "linux/amd64") ARCH="amd64" ;; \
        "linux/arm64") ARCH="arm64" ;; \
        *) echo "Unsupported platform: $TARGETPLATFORM" && exit 1 ;; \
    esac && \
    wget -O mcp-mesh.tar.gz "https://github.com/dhyansraj/mcp-mesh/releases/download/${VERSION}/mcp-mesh_${VERSION}_linux_${ARCH}.tar.gz" && \
    tar -xzf mcp-mesh.tar.gz && \
    cp linux_${ARCH}/meshui-dashboard /usr/local/bin/meshui && \
    chmod +x /usr/local/bin/meshui && \
    rm -rf mcp-mesh.tar.gz linux_${ARCH}

# Create data directory for database
RUN mkdir -p /data && chown mcp-mesh:mcp-mesh /data

# Switch to non-root user
USER mcp-mesh

ENV MCP_MESH_UI_BASE_PATH=/ops/dashboard

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3080/ops/dashboard/api/ui-health || exit 1

EXPOSE 3080

ENTRYPOINT ["/usr/local/bin/meshui"]
CMD ["--port", "3080"]
