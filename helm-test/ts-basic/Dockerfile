# Dockerfile for ts-basic MCP Mesh agent
FROM mcpmesh/typescript-runtime:0.8

WORKDIR /app

# Switch to root to copy files (base image runs as non-root mcp-mesh user)
USER root

# Copy package files and install app-specific dependencies only
COPY package*.json ./
RUN npm ci --omit=dev

# Copy agent source code and set permissions
COPY --chmod=755 . .
RUN chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user for security
USER mcp-mesh

# Expose the agent port
EXPOSE 8080

# Run the agent
# NOTE: Base image has ENTRYPOINT ["npx", "tsx"], so CMD only needs the script path
CMD ["src/index.ts"]
