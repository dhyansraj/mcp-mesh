# Multi-stage build for MCP Mesh Registry
# Supports linux/amd64, linux/arm64

FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS builder

ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG TARGETOS
ARG TARGETARCH

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

# Copy go mod files first for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . ./

# Build for target architecture
ENV CGO_ENABLED=0
ENV GOOS=$TARGETOS
ENV GOARCH=$TARGETARCH

RUN go build -ldflags="-w -s" -o registry ./cmd/mcp-mesh-registry

# Final stage - minimal runtime image
FROM --platform=$TARGETPLATFORM alpine:3.19

# Install runtime dependencies
RUN apk add --no-cache \
    ca-certificates \
    tzdata \
    sqlite \
    && addgroup -g 1001 -S mcp-mesh \
    && adduser -u 1001 -S mcp-mesh -G mcp-mesh

# Copy binary from builder
COPY --from=builder /build/registry /usr/local/bin/registry

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
