# Dependency Agent (Java)

An MCP Mesh agent demonstrating `@MeshTool` dependencies with mesh injection.

## What This Example Shows

- `@MeshTool(dependencies = ...)` - Declaring required capabilities
- `McpMeshTool` injection - Mesh proxy automatically injected into tool methods
- Graceful degradation - Fallback when dependency unavailable
- Auto-rewiring - Proxy updates when topology changes

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

### 2. (Optional) Start a Date Service Provider

For full dependency injection, start a date_service provider:

```bash
# Using Python example
meshctl start -d examples/date-service/date_service.py

# Or any agent that exposes capability="date_service"
```

### 3. Run the Agent

```bash
cd examples/java/dependency-agent

# With Maven
mvn spring-boot:run

# Or build and run JAR
mvn package
java -jar target/dependency-agent-1.0.0-SNAPSHOT.jar
```

### 4. Test with meshctl

```bash
# List agents
meshctl list
# Output: assistant  healthy  http://localhost:9001

# List tools
meshctl list -t
# Output: smart_greeting, agent_status

# Call smart_greeting (uses date_service if available, else fallback)
meshctl call smart_greeting '{"name": "World"}'

# Check agent status with dependency info
meshctl call agent_status '{}'
```

## Testing Graceful Degradation

```bash
# 1. Without date_service - uses local fallback
meshctl call smart_greeting '{"name": "Alice"}'
# Output: {"message": "Hello, Alice! Today is 2026-01-29", "source": "local fallback", ...}

# 2. Start date_service
meshctl start -d examples/date-service/date_service.py

# 3. Wait for topology update, then call again - uses mesh service
meshctl call smart_greeting '{"name": "Alice"}'
# Output: {"message": "Hello, Alice! Today is Wednesday, January 29, 2026", "source": "mesh:date_service", ...}

# 4. Stop date_service, call again - falls back gracefully
meshctl stop date-service
meshctl call smart_greeting '{"name": "Alice"}'
# Output: {"message": "Hello, Alice! Today is 2026-01-29", "source": "local fallback", ...}
```

## Configuration

Override settings via environment variables:

| Variable                | Description     | Default                 |
| ----------------------- | --------------- | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL    | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port | `9001`                  |
| `MCP_MESH_AGENT_NAME`   | Agent name      | `assistant`             |
| `MCP_MESH_NAMESPACE`    | Mesh namespace  | `default`               |

Example:

```bash
MCP_MESH_HTTP_PORT=9010 MCP_MESH_AGENT_NAME=assistant-2 mvn spring-boot:run
```

## Code Structure

```
src/main/java/com/example/assistant/
└── AssistantAgentApplication.java   # Main app with @MeshTool dependencies

src/main/resources/
└── application.yml                  # Spring Boot configuration

src/test/java/com/example/assistant/
└── AssistantAgentTest.java          # Unit tests with mocks
```

## Tools Provided

### `smart_greeting`

Greet with current date from mesh dependency.

**Dependencies:**

- `date_service` capability (optional - graceful degradation if unavailable)

**Parameters:**

- `name` (string, required): The name to greet

**Response:**

```json
{
  "message": "Hello, Alice! Today is Wednesday, January 29, 2026",
  "timestamp": "2026-01-29T12:00:00",
  "source": "mesh:date_service"
}
```

### `agent_status`

Get agent status with dependency information.

**Dependencies:**

- `date_service` capability (optional)

**Parameters:** None

**Response:**

```json
{
  "name": "assistant",
  "version": "1.0.0",
  "runtime": "Java 17.0.1",
  "platform": "Mac OS X",
  "dateServiceAvailable": true,
  "dateServiceEndpoint": "http://localhost:9002"
}
```

## Key Concepts

### McpMeshTool Injection

When you declare a dependency with `@Selector`, the mesh injects a proxy:

```java
@MeshTool(
    capability = "smart_greeting",
    dependencies = @Selector(capability = "date_service")
)
public GreetingResponse smartGreet(
    @Param("name") String name,
    McpMeshTool dateService  // <-- Automatically injected by mesh
) {
    if (dateService != null && dateService.isAvailable()) {
        // Call remote service via mesh
        Map<String, Object> result = dateService.call(Map.of("format", "long"));
        String date = (String) result.get("date");
        // ...
    } else {
        // Graceful degradation - use local fallback
    }
}
```

### Calling Mesh Tools

The `McpMeshTool` proxy supports multiple calling styles:

```java
// With Map
dateService.call(Map.of("format", "long", "timezone", "UTC"));

// With varargs
dateService.call("format", "long", "timezone", "UTC");

// No parameters
dateService.call();

// Async
CompletableFuture<Map<String, Object>> future = dateService.callAsync(Map.of(...));
```

### Graceful Degradation

Always check availability before calling:

```java
if (dateService != null && dateService.isAvailable()) {
    // Use mesh service
} else {
    // Use local fallback
}
```
