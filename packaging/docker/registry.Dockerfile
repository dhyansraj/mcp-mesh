# MCP Mesh Registry - Multi-stage build with CGO support
# Supports linux/amd64, linux/arm64

# Build stage
FROM --platform=$TARGETPLATFORM golang:1.23-alpine AS builder

ARG TARGETPLATFORM
ARG VERSION
ARG TARGETOS
ARG TARGETARCH

WORKDIR /build

# Install build dependencies (including SQLite build tools)
RUN apk add --no-cache \
    git \
    ca-certificates \
    tzdata \
    gcc \
    musl-dev \
    sqlite-dev \
    build-base

# Download source from GitHub release
RUN if [ -n "$VERSION" ]; then \
        wget -O source.tar.gz "https://github.com/dhyansraj/mcp-mesh/archive/v${VERSION}.tar.gz" && \
        tar --strip-components=1 -xzf source.tar.gz && \
        rm source.tar.gz; \
    else \
        echo "VERSION build arg is required" && exit 1; \
    fi

# Build for target architecture with SQLite support
ENV CGO_ENABLED=1
ENV CGO_CFLAGS="-D_LARGEFILE64_SOURCE"
ENV GOOS=$TARGETOS
ENV GOARCH=$TARGETARCH

RUN go mod download && \
    go build -tags "sqlite_omit_load_extension" -ldflags="-w -s" -o registry ./cmd/mcp-mesh-registry

# Final stage - minimal runtime image
FROM --platform=$TARGETPLATFORM alpine:3.19

# Install runtime dependencies (including wget for health checks)
RUN apk add --no-cache \
    ca-certificates \
    tzdata \
    sqlite \
    wget \
    && addgroup -g 1001 -S mcp-mesh \
    && adduser -u 1001 -S mcp-mesh -G mcp-mesh

# Copy binary from builder stage
COPY --from=builder /build/registry /usr/local/bin/registry

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
