# Prerequisites

> What you need before building MCP Mesh agents with Java

**MCP Mesh supports Python, Java, and TypeScript.** Choose the language that fits your needs—or use all three in the same mesh.

## Windows Users

`meshctl` and `mcp-mesh-registry` require a Unix-like environment on Windows:

- **WSL2** (recommended) - Full Linux environment
- **Git Bash** - Lightweight option

Alternatively, use Docker Desktop for containerized development.

## Local Development

### Java 17+

```bash
# Check version
java --version  # Need 17+

# Install if needed
brew install openjdk@17          # macOS
sudo apt install openjdk-17-jdk  # Ubuntu/Debian
```

### Maven 3.8+

```bash
# Check version
mvn --version

# Install if needed
brew install maven               # macOS
sudo apt install maven           # Ubuntu/Debian
```

### MCP Mesh Java SDK

Add the Spring Boot starter to your `pom.xml`:

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.2</version>
</parent>

<dependencies>
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>0.9.3</version>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
</dependencies>
```

### meshctl CLI

```bash
npm install -g @mcpmesh/cli

# Verify
meshctl --version
```

### Quick Start (Java)

```bash
# 1. Scaffold a Java agent
meshctl scaffold --name hello --agent-type basic --lang java

# 2. Run with meshctl (detects pom.xml, supports --debug/--watch)
meshctl start hello/ --debug

# 3. Test
meshctl list
meshctl call hello greeting --params '{"name": "World"}'
```

## Docker Deployment

For containerized deployments.

### Docker & Docker Compose

```bash
# Check installation
docker --version
docker compose version
```

### MCP Mesh Images

| Image                            | Description                 |
| -------------------------------- | --------------------------- |
| `mcpmesh/registry:0.9`           | Registry service            |
| `mcpmesh/python-runtime:0.9`     | Python runtime with SDK     |
| `mcpmesh/java-runtime:0.9`       | Java runtime with SDK       |
| `mcpmesh/typescript-runtime:0.9` | TypeScript runtime with SDK |

Java agents use standard Maven-based Docker builds (see Docker Deployment guide).

## Kubernetes Deployment

For production Kubernetes clusters.

### kubectl & Helm

```bash
kubectl version --client
helm version
```

## Version Compatibility

| Component   | Minimum | Recommended |
| ----------- | ------- | ----------- |
| Java        | 17      | 21          |
| Maven       | 3.8     | 3.9+        |
| Spring Boot | 3.2     | 4.0+        |
| Docker      | 20.10   | Latest      |
| Kubernetes  | 1.25    | 1.28+       |
| Helm        | 3.10    | 3.14+       |

## See Also

- `meshctl man deployment --java` - Deployment patterns
- `meshctl man environment` - Configuration options
- `meshctl scaffold --help` - Generate agents
