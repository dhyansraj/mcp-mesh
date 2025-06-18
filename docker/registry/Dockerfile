FROM golang:1.23-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    git \
    gcc \
    musl-dev \
    sqlite-dev \
    build-base

# Set working directory
WORKDIR /src

# Copy the entire project source
COPY . .

# Set environment variables for SQLite compilation on Alpine/musl
ENV CGO_ENABLED=1
ENV CGO_CFLAGS="-D_LARGEFILE64_SOURCE"

# Build the registry binary with SQLite compatibility flags
RUN cd cmd/mcp-mesh-registry && \
    go build -tags "sqlite_omit_load_extension" -ldflags="-s -w" -o mcp-mesh-registry .

# Runtime stage
FROM alpine:latest

# Install runtime dependencies
RUN apk --no-cache add ca-certificates sqlite wget

# Create directory for the database
RUN mkdir -p /data

# Create app user for security
RUN adduser -D -u 1000 appuser && \
    chown -R appuser:appuser /data

# Copy the binary from builder
COPY --from=builder /src/cmd/mcp-mesh-registry/mcp-mesh-registry /usr/local/bin/

# Switch to app user
USER appuser

# Set working directory
WORKDIR /data

# Expose the registry port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

# Start the registry
CMD ["mcp-mesh-registry"]
