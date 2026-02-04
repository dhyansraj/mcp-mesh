# Basic Tool Agent (Java)

A simple MCP Mesh agent demonstrating `@MeshAgent` and `@MeshTool` annotations.

## What This Example Shows

- `@MeshAgent` - Configure agent name, port, and metadata
- `@MeshTool` - Register a method as a mesh capability
- `@Param` - Document tool parameters
- Java records for structured responses

## Prerequisites

1. Build the MCP Mesh Java SDK:

   ```bash
   cd src/runtime/java
   mvn install -DskipTests
   ```

2. Build the Rust FFI library (optional, for full integration):
   ```bash
   cd src/runtime/core
   cargo build --no-default-features --features ffi --release
   ```

## Running

### 1. Start the Registry

```bash
meshctl start --registry-only
```

### 2. Run the Agent

```bash
cd examples/java/basic-tool-agent

# With Maven
mvn spring-boot:run

# Or build and run JAR
mvn package
java -jar target/basic-tool-agent-1.0.0-SNAPSHOT.jar
```

### 3. Test with meshctl

```bash
# List agents
meshctl list
# Output: greeter  healthy  http://localhost:9000

# List tools
meshctl list -t
# Output: greeting  Greet a user by name

# Call the greeting tool
meshctl call greeting '{"name": "World"}'
# Output: {"message": "Hello, World! Welcome to MCP Mesh.", ...}

# Get agent info
meshctl call agent_info '{}'
```

## Configuration

Override settings via environment variables:

| Variable                | Description     | Default                 |
| ----------------------- | --------------- | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL    | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port | `9000`                  |
| `MCP_MESH_AGENT_NAME`   | Agent name      | `greeter`               |
| `MCP_MESH_NAMESPACE`    | Mesh namespace  | `default`               |

Example:

```bash
MCP_MESH_HTTP_PORT=9001 MCP_MESH_AGENT_NAME=greeter-2 mvn spring-boot:run
```

## Code Structure

```
src/main/java/com/example/greeter/
└── GreeterAgentApplication.java   # Main app with @MeshAgent and @MeshTool

src/main/resources/
└── application.yml                # Spring Boot configuration

src/test/java/com/example/greeter/
└── GreeterAgentTest.java          # Unit tests
```

## Tools Provided

### `greeting`

Greet a user by name.

**Parameters:**

- `name` (string, required): The name to greet

**Response:**

```json
{
  "message": "Hello, Alice! Welcome to MCP Mesh.",
  "timestamp": "2026-01-29T12:00:00",
  "source": "greeter-java"
}
```

### `agent_info`

Get information about this agent.

**Parameters:** None

**Response:**

```json
{
  "name": "greeter",
  "version": "1.0.0",
  "runtime": "Java 17.0.1",
  "platform": "Mac OS X"
}
```
