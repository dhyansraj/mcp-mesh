# MCP Mesh UI Server - Source build with custom basePath
# Use this when you need path-based ingress routing (e.g., /ops/dashboard)
#
# Build:
#   docker build -f packaging/docker/ui-custom.Dockerfile \
#     --build-arg UI_BASE_PATH=/ops/dashboard \
#     -t mcpmesh/ui:custom .
#
# The default image (mcpmesh/ui) serves at root "/".
# This Dockerfile rebuilds the SPA with a custom basePath baked in.

# Stage 1: Build Next.js SPA with basePath
FROM node:22-alpine AS ui-builder
ARG UI_BASE_PATH=""
WORKDIR /src/ui
COPY src/ui/package.json src/ui/package-lock.json ./
RUN npm ci --silent
COPY src/ui/ ./
ENV NEXT_PUBLIC_UI_BASE_PATH=${UI_BASE_PATH}
RUN npm run build

# Stage 2: Build Go binary with embedded SPA
FROM golang:1.25-alpine AS go-builder
ARG UI_BASE_PATH=""
RUN apk add --no-cache git gcc musl-dev sqlite-dev build-base
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Replace embedded SPA with basePath-configured build
COPY --from=ui-builder /src/ui/out cmd/mcp-mesh-ui/out/
ENV CGO_ENABLED=1
ENV CGO_CFLAGS="-D_LARGEFILE64_SOURCE"
RUN cd cmd/mcp-mesh-ui && \
    go build -tags "sqlite_omit_load_extension" -ldflags="-s -w" -o meshui .

# Stage 3: Minimal runtime
FROM alpine:3.21
RUN apk --no-cache add ca-certificates sqlite wget
RUN adduser -D -u 1000 appuser && mkdir -p /data && chown appuser:appuser /data
COPY --from=go-builder /src/cmd/mcp-mesh-ui/meshui /usr/local/bin/
USER appuser
WORKDIR /data

ARG UI_BASE_PATH=""
ENV MCP_MESH_UI_BASE_PATH=${UI_BASE_PATH}

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3080${UI_BASE_PATH}/api/ui-health || exit 1

EXPOSE 3080
ENTRYPOINT ["/usr/local/bin/meshui"]
CMD ["--port", "3080"]
