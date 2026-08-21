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
    <version>3.6.0</version>
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
    image: mcpmesh/registry:3.6.0
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
# --create-namespace creates the namespace; the chart renders none of its
# own. Run `meshctl man deployment` for the namespace rules, including
# the upgrade order for a release installed with chart 3.4.x or earlier.
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 3.6.0 \
  -n mcp-mesh --create-namespace

# Deploy Java agent
helm install my-agent oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  --version 3.6.0 \
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
  --version 3.6.0 \
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

Spring Actuator is not a starter dependency, and mesh contributes nothing to it. If your application adds Actuator itself, `/actuator/health` aggregates every registered indicator - datasource, disk, mail - so it is not a substitute for `/ready`: gating mesh traffic on it gates on conditions the agent's author never intended to affect routing.

The starter serves the four mesh endpoints, and Kubernetes probes must not share one:

- `/startupz` - `startupProbe`. Reports your `@MeshStartupCheck`; an agent that declares none passes.
- `/livez` - `livenessProbe`. 200 for as long as the process is serving; consults nothing else.
- `/ready` - `readinessProbe`. Whether the mesh runtime is up, on every agent type. Your `@MeshHealthCheck` does not reach it: a failing check pauses the heartbeat and the registry stops resolving to this agent, which is the whole withdrawal, and a 503 here would also empty the Service that mesh traffic arrives on.
- `/health` - no probe. Your check's verdict plus the `checks` and `errors` it returned, 503 while the verdict is not healthy.

Both `/health` and `/ready` answer 503 until the mesh runtime is up - it starts late in the Spring lifecycle - so pointing liveness at either restarts pods that are merely still booting. Probe Wiring below has the manifest.

Annotate one no-argument method with `@MeshHealthCheck` to say what "ready" means for this agent:

```java
@MeshHealthCheck(ttlSeconds = 30)
public MeshHealth healthCheck() {
    if (!vendorReachable()) {
        return MeshHealth.unhealthy("vendor API unreachable")
            .withCheck("vendor_api_reachable", false);
    }
    return MeshHealth.healthy().withCheck("vendor_api_reachable", true);
}
```

While the check returns unhealthy the agent stops heartbeating, the registry withdraws it, and consumers resolve to another provider - restored automatically when the check passes, with no restart. Returning `boolean` works too: `true` is healthy, `false` unhealthy. A check that throws keeps heartbeating, so a bug in the check cannot take a working agent out of the mesh. `MCP_MESH_HEALTH_CHECK_TTL` overrides `ttlSeconds`.

Route-only (`api`) and A2A agents are no exception: their check pauses the heartbeat too, so the registry stops advertising the gateway. It keeps serving the ingress it already had - `/ready` reports the mesh runtime on every agent type, so the pod keeps its Service endpoints. Both hooks are declared the same way there, on any Spring bean, and the starter serves the four paths below from one controller whatever the agent type - so a `@GetMapping` of your own for any of them is an ambiguous mapping and the application does not start.

### Probe Wiring

The agent chart already wires all three probes. If you write your own Deployment, wire them the same way - the paths are the whole contract:

```yaml
startupProbe:
  httpGet:
    path: /startupz
    port: 8080
  periodSeconds: 10
  failureThreshold: 30

livenessProbe:
  httpGet:
    path: /livez
    port: 8080
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  periodSeconds: 5
  failureThreshold: 3
```

Never point `livenessProbe` or `startupProbe` at `/ready` or `/health`. The failure action of both probes is a container restart, and a restart cannot fix what either endpoint reports:

- `livenessProbe: /health` - a dependency outage answers 503, the default `failureThreshold` of three kills the pod, and the replacement finds the same dependency still down.
- `startupProbe: /ready` - readiness reports the mesh runtime, not whether this agent has finished starting, and it goes down again on every shutdown. `/startupz` is the endpoint whose failure a restart is the right response to, and unlike `/ready` it is not gated on a runtime that starts late in the Spring lifecycle.

`/actuator/health` is not an option either, for the reason above: a liveness probe pointed there restarts the pod for whatever an unrelated indicator reports.

Nothing probes `/health`. It is the diagnostic view: curl it from `kubectl exec` to see the `checks` and `errors` behind a `@MeshHealthCheck` that has withdrawn an agent.

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
