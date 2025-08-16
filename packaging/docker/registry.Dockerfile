# MCP Mesh Registry - Downloads pre-built binary from GitHub releases
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM debian:12-slim

ARG TARGETPLATFORM
ARG VERSION

# Install runtime dependencies (including wget for health checks)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    tzdata \
    sqlite3 \
    wget \
    && groupadd -g 1001 mcp-mesh \
    && useradd -u 1001 -g mcp-mesh mcp-mesh \
    && rm -rf /var/lib/apt/lists/*

# Download and extract registry binary based on platform
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    case "$TARGETPLATFORM" in \
        "linux/amd64") ARCH="amd64" ;; \
        "linux/arm64") ARCH="arm64" ;; \
        *) echo "Unsupported platform: $TARGETPLATFORM" && exit 1 ;; \
    esac && \
    wget -O registry.tar.gz "https://github.com/dhyansraj/mcp-mesh/releases/download/${VERSION}/mcp-mesh_${VERSION}_linux_${ARCH}.tar.gz" && \
    tar -xzf registry.tar.gz && \
    cp linux_${ARCH}/mcp-mesh-registry /usr/local/bin/registry && \
    chmod +x /usr/local/bin/registry && \
    rm -rf registry.tar.gz linux_${ARCH}

# Create data directory
RUN mkdir -p /data && chown mcp-mesh:mcp-mesh /data

# Switch to non-root user
USER mcp-mesh

# Set database path to use /data volume
ENV DATABASE_URL=/data/mcp_mesh_registry.db

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

EXPOSE 8000
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/registry"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
