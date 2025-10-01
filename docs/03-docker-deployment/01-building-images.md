# Building Docker Images

> Create optimized, secure Docker images for your MCP Mesh agents

## Overview

Building proper Docker images is crucial for reliable agent deployment. This guide covers creating efficient Dockerfiles, optimizing image size, implementing security best practices, and building images that work seamlessly with MCP Mesh's service discovery.

We'll explore both simple single-agent images and complex multi-stage builds, ensuring your agents are production-ready.

## Key Concepts

- **Base Images**: Choosing the right starting point (python:slim, alpine, distroless)
- **Layer Caching**: Optimizing build speed with proper layer ordering
- **Multi-Stage Builds**: Reducing image size by separating build and runtime
- **Security**: Running as non-root, scanning for vulnerabilities
- **MCP Mesh Integration**: Ensuring agents can register and communicate

## Step-by-Step Guide

### Step 1: Basic Agent Dockerfile

Create a simple Dockerfile for your agent:

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install MCP Mesh from source
COPY . .
RUN make install-dev

# Agent code is already copied above

# Create non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app

USER mcp

# Expose agent port (if using HTTP)
EXPOSE 8888

# Set environment variables
ENV MCP_MESH_LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# Run the agent
CMD ["./bin/meshctl", "start", "examples/simple/my_agent.py"]
```

Build and test:

```bash
docker build -t my-agent:latest .
docker run --rm my-agent:latest
```

### Step 2: Multi-Stage Build for Optimization

Reduce image size with multi-stage builds:

```dockerfile
# Dockerfile.multistage
# Build stage
FROM python:3.11 AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git

# Install MCP Mesh dependencies
COPY . .
RUN make build && make install-dev

# Run any build steps (compile, minimize, etc.)
RUN python -m compileall examples/

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy built binaries and agent code
COPY --from=builder /build/bin ./bin
COPY --from=builder /build/examples ./examples
COPY --from=builder /build/src ./src

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app

USER mcp

EXPOSE 8888

CMD ["./bin/meshctl", "start", "examples/simple/my_agent.py"]
```

### Step 3: MCP Mesh Specific Configuration

Ensure your image works with MCP Mesh:

```dockerfile
# Dockerfile.mcp-mesh
FROM python:3.11-slim

WORKDIR /app

# Install MCP Mesh from source
COPY . .
RUN make install-dev

# Agent examples are already available

# Create directories for MCP Mesh
RUN mkdir -p /data /etc/mcp-mesh /var/log/mcp-mesh

# Add health check script
COPY docker/healthcheck.py /usr/local/bin/
RUN chmod +x /usr/local/bin/healthcheck.py

# Configure health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s \
  CMD python /usr/local/bin/healthcheck.py || exit 1

# Create non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app /data /etc/mcp-mesh /var/log/mcp-mesh

USER mcp

# MCP Mesh environment variables
ENV MCP_MESH_REGISTRY_URL=http://registry:8000
ENV MCP_MESH_LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

EXPOSE 8888

# Use exec form for proper signal handling
ENTRYPOINT ["./bin/meshctl"]
CMD ["start", "examples/simple/my_agent.py"]
```

### Step 4: Build Arguments and Flexibility

Make images configurable with build arguments:

```dockerfile
# Dockerfile.flexible
ARG PYTHON_VERSION=3.11
ARG BASE_IMAGE=python:${PYTHON_VERSION}-slim

FROM ${BASE_IMAGE}

# Build arguments
ARG AGENT_NAME=my-agent
ARG AGENT_PORT=8888
ARG BUILD_DATE
ARG VCS_REF

# Labels for metadata
LABEL org.opencontainers.image.title="MCP Mesh Agent: ${AGENT_NAME}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="1.0.0"

WORKDIR /app

# Dynamic configuration based on build args
ENV AGENT_NAME=${AGENT_NAME}
ENV AGENT_PORT=${AGENT_PORT}

# Rest of Dockerfile...
EXPOSE ${AGENT_PORT}
```

Build with arguments:

```bash
docker build \
  --build-arg AGENT_NAME=weather-agent \
  --build-arg AGENT_PORT=9000 \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  --build-arg VCS_REF=$(git rev-parse HEAD) \
  -t weather-agent:latest .
```

## Configuration Options

| Build Arg        | Description           | Default          | Example                  |
| ---------------- | --------------------- | ---------------- | ------------------------ |
| `PYTHON_VERSION` | Python version to use | 3.11             | 3.10, 3.12               |
| `AGENT_NAME`     | Name for the agent    | agent            | weather-agent            |
| `AGENT_PORT`     | Port to expose        | 8888             | 9000                     |
| `BASE_IMAGE`     | Base image to use     | python:3.11-slim | python:3.11-alpine       |
| `PIP_INDEX_URL`  | Custom pip repository | -                | https://pypi.company.com |

## Examples

### Example 1: Production-Ready Image

```dockerfile
# Dockerfile.production
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

FROM gcr.io/distroless/python3-debian11

WORKDIR /app

# Copy wheels and install
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN python -m pip install --no-cache /wheels/*

# Copy application
COPY --chown=nonroot:nonroot agents/ ./agents/

# Use distroless nonroot user
USER nonroot

EXPOSE 8888

ENTRYPOINT ["./bin/meshctl", "start"]
CMD ["examples/simple/production_agent.py"]
```

### Example 2: Development Image with Tools

```dockerfile
# Dockerfile.dev
FROM python:3.11

WORKDIR /app

# Install development tools
RUN apt-get update && apt-get install -y \
    vim \
    htop \
    net-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Install MCP Mesh in development mode
COPY . .
RUN make install-dev

# Development tools are included in make install-dev

# Everything is already copied above

# Keep container running for debugging
CMD ["tail", "-f", "/dev/null"]
```

## Best Practices

1. **Order Layers by Change Frequency**: Put rarely-changing items first
2. **Minimize Layer Count**: Combine RUN commands with &&
3. **Clean Up in Same Layer**: Remove temp files in the same RUN command
4. **Use .dockerignore**: Exclude unnecessary files from build context
5. **Pin Versions**: Specify exact versions for reproducibility

## Common Pitfalls

### Pitfall 1: Large Image Size

**Problem**: Image is several GB due to build tools and caches

**Solution**: Use multi-stage builds and clean up:

```dockerfile
# Bad
RUN apt-get update
RUN apt-get install build-essential
RUN pip install numpy

# Good
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    pip install --no-cache-dir numpy && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
```

### Pitfall 2: Secrets in Image

**Problem**: API keys or passwords baked into image

**Solution**: Use environment variables or secrets management:

```dockerfile
# Bad
ENV API_KEY=secret123

# Good
# Pass at runtime: docker run -e API_KEY=$API_KEY
```

## Testing

### Unit Test Example

```bash
# test_docker_build.sh
#!/bin/bash

# Test build succeeds
docker build -t test-agent:latest . || exit 1

# Test CLI works
docker run --rm test-agent:latest ./bin/meshctl --version || exit 1

# Test as non-root
docker run --rm test-agent:latest whoami | grep -q "mcp" || exit 1

# Test health check
docker run -d --name test-health test-agent:latest
sleep 5
docker inspect test-health --format='{%raw%}{{.State.Health.Status}}{%endraw%}' | grep -q "healthy" || exit 1
docker rm -f test-health
```

### Integration Test Example

```python
# tests/test_docker_agent.py
import docker
import requests
import time

def test_agent_in_docker():
    client = docker.from_env()

    # Run agent container
    container = client.containers.run(
        "my-agent:latest",
        detach=True,
        ports={'8888/tcp': 8888},
        environment={'MCP_MESH_LOG_LEVEL': 'DEBUG'}
    )

    try:
        # Wait for startup
        time.sleep(5)

        # Test health endpoint
        response = requests.get('http://localhost:8888/health')
        assert response.status_code == 200

    finally:
        container.stop()
        container.remove()
```

## Monitoring and Debugging

### Build Performance

```bash
# Enable BuildKit for better output
DOCKER_BUILDKIT=1 docker build .

# Analyze build cache usage
docker system df

# Show build history
docker history my-agent:latest
```

### Image Analysis

```bash
# Check image size and layers
docker images my-agent:latest
docker inspect my-agent:latest | jq '.[0].RootFS.Layers | length'

# Security scanning
docker scan my-agent:latest

# Explore image contents
docker run --rm -it my-agent:latest sh
```

## 🔧 Troubleshooting

### Issue 1: Build Fails with Permission Denied

**Symptoms**: Cannot create directories or write files

**Cause**: Running as root then switching users

**Solution**:

```dockerfile
# Create directories before switching user
RUN mkdir -p /app /data && \
    chown -R mcp:mcp /app /data

USER mcp
```

### Issue 2: Agent Can't Connect to Registry

**Symptoms**: "Connection refused" to registry

**Cause**: Using localhost in container

**Solution**:

```dockerfile
# Use service name in Docker network
ENV MCP_MESH_REGISTRY_URL=http://registry:8000
# Not: http://localhost:8000
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Alpine Linux**: Some Python packages require glibc, not musl
- **Distroless**: Limited debugging capabilities
- **File Permissions**: UID/GID mapping issues on some systems
- **Signal Handling**: PID 1 requires special handling

## 📝 TODO

- [ ] Add examples for GPU-enabled agents
- [ ] Document rootless container builds
- [ ] Add supply chain security (SBOM)
- [ ] Create CI/CD pipeline examples
- [ ] Add image signing documentation

## Summary

You can now build optimized Docker images for MCP Mesh agents with:

Key takeaways:

- 🔑 Efficient Dockerfiles with proper layering
- 🔑 Security best practices with non-root users
- 🔑 Multi-stage builds for minimal image size
- 🔑 MCP Mesh specific configuration and health checks

## Next Steps

Now let's orchestrate multiple agents with Docker Compose.

Continue to [Docker Compose Setup](./02-compose-setup.md) →

---

💡 **Tip**: Use `dive` to analyze and optimize your Docker images: `dive my-agent:latest`

📚 **Reference**: [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

🧪 **Try It**: Build an image under 100MB using Alpine or distroless as the base
