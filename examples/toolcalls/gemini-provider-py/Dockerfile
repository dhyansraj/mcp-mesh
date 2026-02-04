# Dockerfile for gemini-provider-py MCP Mesh LLM provider
FROM mcpmesh/python-runtime:0.8

WORKDIR /app

# Switch to root to copy files (base image runs as non-root mcp-mesh user)
USER root

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source code and set permissions
COPY --chmod=755 . .
RUN chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user for security
USER mcp-mesh

# Expose the agent port
EXPOSE 9000

# Run the agent
# NOTE: Base image has ENTRYPOINT ["python"], so CMD only needs the script name
CMD ["main.py"]
