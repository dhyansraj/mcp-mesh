# Build stage - using debian for better compatibility
FROM golang:1.23-bookworm AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY cmd/ cmd/
COPY src/ src/

# Build the binary
RUN CGO_ENABLED=1 GOOS=linux GOARCH=arm64 go build -o mcp-mesh-registry ./cmd/mcp-mesh-registry

# Runtime stage - minimal debian
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 mcp

# Create necessary directories
RUN mkdir -p /data /etc/mcp-mesh && \
    chown -R mcp:mcp /data /etc/mcp-mesh

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/mcp-mesh-registry /app/mcp-mesh-registry

# Switch to non-root user
USER mcp

# Expose ports
EXPOSE 8080 9090

# Set default environment variables
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DATABASE_URL=/data/registry.db \
    LOG_LEVEL=info \
    HEALTH_CHECK_INTERVAL=30 \
    CACHE_TTL=30

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/app/mcp-mesh-registry", "-version"]

# Run the registry
ENTRYPOINT ["/app/mcp-mesh-registry"]
