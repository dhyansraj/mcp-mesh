# Testing MCP Agents (Java/Spring Boot)

> How to test Java/Spring Boot MCP Mesh agents

## Quick Way: meshctl call

```bash
meshctl call greeting '{"name": "World"}'        # Call tool by name
meshctl call add '{"a": 1, "b": 2}'              # With arguments
meshctl list --tools                              # List all available tools
```

See `meshctl man cli` for more CLI commands.

## Starting Java Agents

### With meshctl (auto-detects pom.xml)

```bash
# Start registry
meshctl start --registry-only --debug

# Start Java agent - meshctl detects pom.xml in the directory
meshctl start examples/java/basic-tool-agent --debug

# Verify
meshctl list
meshctl list --tools
```

### With Maven directly

```bash
cd examples/java/basic-tool-agent
mvn spring-boot:run

# With custom port
MCP_MESH_HTTP_PORT=9001 mvn spring-boot:run
```

## Integration Testing with meshctl

End-to-end testing using the CLI:

```bash
# 1. Start registry
meshctl start --registry-only

# 2. Start agent under test
meshctl start examples/java/basic-tool-agent

# 3. Wait for registration
sleep 5

# 4. Verify agent is registered
meshctl list | grep greeter

# 5. Call tools and verify responses
meshctl call greeting '{"name": "Test"}'
meshctl call agent_info

# 6. Cleanup
meshctl stop
```

## JUnit Testing with Spring Boot Test

Use `@SpringBootTest` to test agents with the full Spring context:

```java
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest
class GreeterAgentTest {

    @Autowired
    private GreeterAgentApplication agent;

    @Test
    void testGreet() {
        var response = agent.greet("World");
        assertNotNull(response);
        assertTrue(response.message().contains("Hello, World!"));
        assertEquals("greeter-java", response.source());
    }

    @Test
    void testAgentInfo() {
        var info = agent.getInfo();
        assertEquals("greeter", info.name());
        assertEquals("1.0.0", info.version());
    }
}
```

### Testing with Dependencies (Graceful Degradation)

```java
@SpringBootTest(properties = {
    "mcp.mesh.registry-url="  // Disable registry for unit tests
})
class AssistantAgentTest {

    @Autowired
    private AssistantAgentApplication agent;

    @Test
    void testSmartGreetWithoutDependency() {
        // With no registry, dateService will be null (graceful degradation)
        var response = agent.smartGreet("Test", null);
        assertNotNull(response);
        assertTrue(response.message().contains("Hello, Test!"));
        assertEquals("local fallback", response.source());
    }
}
```

## Testing with Docker Compose

```yaml
# docker-compose.test.yml
services:
  registry:
    image: mcpmesh/registry:0.8
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 5

  agent-under-test:
    build: .
    depends_on:
      registry:
        condition: service_healthy
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
```

```bash
# Run integration tests
docker compose -f docker-compose.test.yml up -d
sleep 10  # Wait for Spring Boot startup

# Test via meshctl
meshctl call greeting '{"name": "Docker"}'

# Cleanup
docker compose -f docker-compose.test.yml down
```

## Protocol Details: curl

MCP agents expose a JSON-RPC 2.0 API over HTTP. Java agents use the same protocol as Python and TypeScript:

### List Available Tools

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

### Call a Tool

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "greeting",
      "arguments": {"name": "World"}
    }
  }'
```

### Parse SSE Response

```bash
| grep "^data:" | sed 's/^data: //' | jq .
```

## Testing Dependencies and Graceful Degradation

Test that your agent handles unavailable dependencies properly:

```java
@Test
void testWithUnavailableDependency() {
    // Pass null to simulate unavailable dependency
    var response = agent.smartGreet("Test", null);

    // Should use fallback, not throw
    assertNotNull(response);
    assertTrue(response.source().contains("fallback"));
}

@Test
void testAgentStatusWithNoDependencies() {
    var status = agent.getStatus(null);

    assertEquals("assistant", status.name());
    assertFalse(status.dateServiceAvailable());
    assertNull(status.dateServiceEndpoint());
}
```

## Running Tests

```bash
# Run all tests
cd examples/java/basic-tool-agent
mvn test

# Run specific test class
mvn test -Dtest=GreeterAgentTest

# Run with verbose output
mvn test -Dsurefire.useFile=false
```

## Available MCP Methods

| Method           | Description                  |
| ---------------- | ---------------------------- |
| `tools/list`     | List all available tools     |
| `tools/call`     | Invoke a tool with arguments |
| `prompts/list`   | List available prompts       |
| `resources/list` | List available resources     |

## See Also

- `meshctl man cli` - CLI commands reference
- `meshctl man decorators --java` - Java annotations
- `meshctl man deployment --java` - Deployment patterns
