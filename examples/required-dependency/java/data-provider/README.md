# data-provider

A MCP Mesh agent generated using `meshctl scaffold`.

## Overview

This is a Java/Spring Boot MCP Mesh agent.

## Getting Started

### Prerequisites

- Java 17+
- Maven 3.9+
- MCP Mesh SDK

### Running the Agent

```bash
mvn spring-boot:run
```

Or with meshctl:

```bash
meshctl start data-provider
```

The agent will start on port 8090 by default.

## Project Structure

```text
data-provider/
├── pom.xml
├── Dockerfile
├── helm-values.yaml
└── src/main/java/com/example/dataprovider/
    └── DataProviderApplication.java
```

## Docker

```bash
# Build the image
docker build -t data-provider:latest .

# Run the container
docker run -p 8090:8090 data-provider:latest
```

## Kubernetes

```bash
# Deploy using Helm
helm install data-provider oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent \
  -n mcp-mesh \
  -f helm-values.yaml \
  --set image.repository=your-registry/data-provider \
  --set image.tag=v1.0.0
```

## Documentation

- [MCP Mesh Documentation](https://github.com/dhyansraj/mcp-mesh)
- [Java SDK Reference](https://github.com/dhyansraj/mcp-mesh/tree/main/src/runtime/java)
- Run `meshctl man decorators --java` for decorator reference

## License

MIT
