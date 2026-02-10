# Deployment Patterns (Java/Spring Boot)

> Local, Docker, and Kubernetes deployment for Java agents

## Overview

MCP Mesh supports multiple deployment patterns for Java/Spring Boot agents. The `meshctl start` command auto-detects `pom.xml` in directories and handles Maven builds automatically.

## Prerequisites

- Java 17+ (`java -version`)
- Maven 3.8+ (`mvn -version`)
- MCP Mesh Spring Boot Starter in `pom.xml`

```xml
<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-spring-boot-starter</artifactId>
    <version>0.9.3</version>
</dependency>
```

## Local Development

### Quick Start

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug

# Terminal 2: Start Java agent (auto-detects pom.xml)
meshctl start examples/java/basic-tool-agent --debug

# Terminal 3: Monitor
watch 'meshctl list'
```

`meshctl start` detects the `pom.xml` in the directory, builds the project with Maven, and starts the Spring Boot application.

### Running Directly with Maven

```bash
cd examples/java/basic-tool-agent
mvn spring-boot:run

# With environment overrides
MCP_MESH_HTTP_PORT=9001 mvn spring-boot:run
```

### Multiple Agents

```bash
# Start multiple Java agents
meshctl start examples/java/basic-tool-agent examples/java/dependency-agent

# Or run directly with different ports
MCP_MESH_HTTP_PORT=8080 mvn -f agent1/pom.xml spring-boot:run &
MCP_MESH_HTTP_PORT=9001 mvn -f agent2/pom.xml spring-boot:run &
```

### Development Workflow

```bash
# Start agent (detaches automatically for Java)
meshctl start examples/java/basic-tool-agent --debug

# Check running agents
meshctl list

# Stop specific agent
meshctl stop greeter

# Stop all agents
meshctl stop
```

## Spring Boot Configuration

### application.yml

```yaml
# src/main/resources/application.yml
server:
  port: ${MCP_MESH_HTTP_PORT:8080}

spring:
  application:
    name: ${MCP_MESH_AGENT_NAME:my-agent}

logging:
  level:
    io.mcpmesh: ${MCP_MESH_LOG_LEVEL:INFO}
```

### Environment Variables

All `@MeshAgent` parameters can be overridden via environment variables:

```bash
export MCP_MESH_AGENT_NAME=custom-name
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_REGISTRY_URL=http://localhost:8000
export MCP_MESH_NAMESPACE=production
```

## Docker Deployment

### Dockerfile (Multi-Stage Build)

```dockerfile
FROM eclipse-temurin:17-jdk-jammy AS build
WORKDIR /app
COPY pom.xml .
COPY src/ src/
RUN mvn package -DskipTests -q

FROM eclipse-temurin:17-jre-jammy
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

### Build and Run

```bash
cd examples/java/basic-tool-agent

# Build image
docker build -t my-java-agent:latest .

# Run with registry
docker run -e MCP_MESH_REGISTRY_URL=http://host.docker.internal:8000 \
    -p 8080:8080 my-java-agent:latest
```

### Docker Compose

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: mesh
      POSTGRES_PASSWORD: mesh
      POSTGRES_DB: mesh
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mesh"]
      interval: 5s
      timeout: 3s
      retries: 5

  registry:
    image: mcpmesh/registry:0.8
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgres://mesh:mesh@postgres:5432/mesh
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 5

  greeter:
    build: ./examples/java/basic-tool-agent
    ports:
      - "8080:8080"
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      MCP_MESH_HTTP_PORT: 8080
    depends_on:
      registry:
        condition: service_healthy

  assistant:
    build: ./examples/java/dependency-agent
    ports:
      - "9001:9001"
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
      MCP_MESH_HTTP_PORT: 9001
    depends_on:
      registry:
        condition: service_healthy
```

```bash
docker compose up -d
docker compose logs -f
docker compose ps
```

## Kubernetes Deployment

### Helm Charts

For production Kubernetes deployment:

```bash
# Install core infrastructure
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.3 \
  -n mcp-mesh --create-namespace

# Deploy Java agent
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.3 \
  -n mcp-mesh \
  -f my-agent/helm-values.yaml
```

### helm-values.yaml for Java

```yaml
image:
  repository: your-registry/my-java-agent
  tag: latest

agent:
  name: my-agent
  command: [] # Empty = use Docker image's CMD (recommended)

mesh:
  enabled: true

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 200m
    memory: 256Mi
```

### Deployment Workflow

```bash
# 1. Build and push Docker image
cd my-agent
docker buildx build --platform linux/amd64 -t your-registry/my-agent:v1.0.0 --push .

# 2. Deploy with Helm
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 0.9.3 \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/my-agent \
  --set image.tag=v1.0.0
```

## Port Strategy

| Environment            | Port Strategy                | Why                                   |
| ---------------------- | ---------------------------- | ------------------------------------- |
| Local / docker-compose | Unique ports (8080, 8081...) | All containers share host network     |
| Kubernetes             | All agents use 8080          | Each pod has its own IP, no conflicts |

The Helm chart sets `MCP_MESH_HTTP_PORT=8080` which overrides `@MeshAgent(port = 8080)`. Your code does not need to change between environments.

## Best Practices

### Health Checks

Spring Boot agents automatically expose `/actuator/health`. The MCP Mesh starter integrates with Spring Boot's health system.

### Graceful Shutdown

Spring Boot handles `SIGINT`/`SIGTERM` automatically. Agents deregister from the registry on shutdown.

### Logging

```bash
# Structured logging for production
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false

# Enable debug logging
export MCP_MESH_LOG_LEVEL=DEBUG
```

### Resource Limits (Kubernetes)

Java agents typically need more memory than Python/TypeScript:

```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "200m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

## See Also

- `meshctl man environment` - Configuration options
- `meshctl man health --java` - Health monitoring
- `meshctl man testing --java` - Testing Java agents
