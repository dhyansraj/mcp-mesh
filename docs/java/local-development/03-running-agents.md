# Run Agents (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../python/local-development/03-running-agents/">Python Run Agents</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/03-running-agents/">TypeScript Run Agents</a></span>
</div>

> Start Java agents with `meshctl start`

## Basic Usage (Recommended)

```bash
# Start a Java agent (point to the project directory containing pom.xml)
meshctl start hello/
```

`meshctl` detects the `pom.xml`, runs `mvn package` if needed, and starts the agent JAR. The registry starts automatically on port 8000 if not already running.

## Debug Mode

Enable verbose logging:

```bash
meshctl start --debug hello/

# Or set specific log level
meshctl start --log-level DEBUG hello/

# Available levels: TRACE, DEBUG, INFO, WARN, ERROR
```

## Hot Reload

Auto-rebuild and restart on code changes:

```bash
meshctl start -w hello/
meshctl start --watch hello/
```

## Background Mode

Run agents in the background (detached):

```bash
# Start in background
meshctl start -d hello/

# View logs
meshctl logs greeter -f

# Stop background agents
meshctl stop --all
```

## Multiple Agents

```bash
# Start multiple agents at once (mixed languages supported)
meshctl start hello/ employee-service/ ../typescript/calculator.ts
```

## Environment Variables

Share configuration across agents:

```bash
# Load from .env file
meshctl start --env-file .env hello/

# Or pass individual variables
meshctl start --env OPENAI_API_KEY=sk-... hello/
```

## Registry Options

```bash
# Start registry only (no agents)
meshctl start --registry-only

# Use custom registry port
meshctl start --registry-port 9000 hello/

# Connect to external registry
meshctl start --registry-url http://remote:8000 hello/
```

## Common Patterns

```bash
# Development: hot reload + debug
meshctl start -w --debug hello/

# CI/Testing: background + quiet
meshctl start -d --quiet hello/

# Production-like: custom registry
meshctl start --registry-url http://registry:8000 hello/
```

## Alternative: Maven / JAR / IDE

For cases where you need to run outside `meshctl` (e.g., attaching a Java debugger from your IDE):

```bash
# 1. Start the registry separately
meshctl start --registry-only

# 2a. Run via Maven
cd hello/
mvn spring-boot:run

# 2b. Or run the JAR directly
cd hello/
mvn package -DskipTests
java -jar target/hello-1.0.0-SNAPSHOT.jar

# 2c. Or run from your IDE (IntelliJ, Eclipse, VS Code)
#     Just run the main class with Spring Boot run configuration
```

!!! info "When to use Maven/IDE directly"
Running via `meshctl start` is preferred because it handles registry lifecycle, port assignment, and log management. Use Maven or IDE only when you need IDE debugging (breakpoints, step-through) or a custom JVM configuration.

## All Options

```bash
meshctl start --help
```

Key flags:

| Flag              | Description                                 |
| ----------------- | ------------------------------------------- |
| `-w, --watch`     | Hot reload on file changes                  |
| `-d, --detach`    | Run in background                           |
| `--debug`         | Enable debug mode                           |
| `--log-level`     | Set log level (TRACE/DEBUG/INFO/WARN/ERROR) |
| `--env-file`      | Load environment from file                  |
| `--env`           | Set individual env var                      |
| `--registry-only` | Start registry without agents               |
| `--registry-port` | Registry port (default: 8000)               |

## Next Steps

Continue to [Inspect the Mesh](./04-inspecting-mesh.md) ->
