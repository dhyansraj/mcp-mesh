# MCP Mesh Registry - Downloads from GitHub releases
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM alpine:3.19

ARG TARGETPLATFORM
ARG VERSION
ARG TARGETOS
ARG TARGETARCH

# Install runtime dependencies
RUN apk add --no-cache \
    ca-certificates \
    tzdata \
    sqlite \
    curl \
    wget \
    bash \
    && addgroup -g 1001 -S mcp-mesh \
    && adduser -u 1001 -S mcp-mesh -G mcp-mesh

# Install registry binary using install.sh script
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing registry ${VERSION} using install.sh..." && \
    curl -sSL "https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh" | bash -s -- --registry-only --version ${VERSION} --install-dir /usr/local/bin

# Create data directory
RUN mkdir -p /data && chown mcp-mesh:mcp-mesh /data

# Switch to non-root user
USER mcp-mesh

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

EXPOSE 8000
VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/registry"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--data-dir", "/data"]
