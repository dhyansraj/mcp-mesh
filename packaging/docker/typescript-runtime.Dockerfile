# MCP Mesh TypeScript Runtime - Installs from npm
# Supports linux/amd64, linux/arm64

FROM --platform=$TARGETPLATFORM node:22-slim

ARG VERSION

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcp-mesh \
    && useradd -r -g mcp-mesh mcp-mesh

# Create app directory
RUN mkdir -p /app && chown mcp-mesh:mcp-mesh /app

WORKDIR /app

# Initialize package.json and install mcp-mesh SDK from npm
RUN if [ -z "$VERSION" ]; then echo "VERSION build arg is required" && exit 1; fi && \
    echo "Installing @mcpmesh/sdk@${VERSION} from npm" && \
    npm init -y && \
    npm install @mcpmesh/sdk@${VERSION}

# Switch to non-root user
USER mcp-mesh

# Health check endpoint (agents will override)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://localhost:8080/health').then(r => r.ok ? process.exit(0) : process.exit(1)).catch(() => process.exit(1))" || exit 1

EXPOSE 8080

# Default entrypoint - agents will override with their scripts
ENTRYPOINT ["node"]
