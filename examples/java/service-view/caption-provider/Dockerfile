# Dockerfile for caption-provider MCP Mesh agent (Java/Spring Boot)
FROM mcpmesh/java-runtime:3.2.3

WORKDIR /app

# Switch to root to copy files
USER root

# Copy Maven config and source
COPY pom.xml .
COPY src/ src/

# Build the application and set permissions
RUN mvn package -DskipTests -q && chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user
USER mcp-mesh

# Expose the agent port
EXPOSE 8110

# Run the agent
# NOTE: Base image has ENTRYPOINT ["java", "-jar"], so CMD only needs the jar path
CMD ["target/caption-provider-1.0.0-SNAPSHOT.jar"]
