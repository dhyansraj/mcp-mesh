# Simple Test Agent - Lightweight for testing
#
# This Dockerfile creates a minimal Python environment for testing agents.
# Mount your agent script as /app/agent.py when running the container.
#
# Example usage:
#   docker run -v ./my_agent.py:/app/agent.py:ro -p 8080:8080 mcp-mesh-test-agent
#
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for basic MCP functionality
RUN pip install --no-cache-dir fastapi uvicorn httpx requests

# Create directories
RUN mkdir -p /data /etc/mcp-mesh

# Non-root user
RUN useradd -m -u 1000 mcp && \
    chown -R mcp:mcp /app /data /etc/mcp-mesh

USER mcp

EXPOSE 8080

# Health check (assumes agent exposes /health endpoint)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command - expects agent.py to be mounted
CMD ["python", "/app/agent.py"]
