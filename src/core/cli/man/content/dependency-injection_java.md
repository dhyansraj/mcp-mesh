# Dependency Injection (Java/Spring Boot)

> Automatic wiring of capabilities between agents

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a tool declares a dependency via `@Selector`, the mesh automatically injects a `McpMeshTool<T>` proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Tool declares dependencies via `@MeshTool(dependencies = @Selector(...))`
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh injects `McpMeshTool<T>` instances as method parameters
5. **Invocation**: Calling the proxy routes to the remote agent

## Declaring Dependencies

### Simple Dependency

```java
@MeshTool(capability = "smart_greeting",
          description = "Greet with current date",
          dependencies = @Selector(capability = "date_service"))
public GreetingResponse smartGreet(
        @Param(value = "name", description = "The name to greet") String name,
        McpMeshTool<String> dateService) {

    if (dateService != null && dateService.isAvailable()) {
        String today = dateService.call();
        return new GreetingResponse("Hello " + name + "! Today is " + today);
    }
    return new GreetingResponse("Hello " + name + "!");
}
```

**Important**: Dependencies are injected as `McpMeshTool<T>` parameters on the method. They may be `null` if unavailable.

### Dependencies with Filters

Use the `@Selector` annotation with tags or version to filter providers:

```java
@MeshTool(capability = "report",
          description = "Generate report with formatted data",
          dependencies = @Selector(capability = "data_service",
                                    tags = {"+fast", "-deprecated"}))
public String generateReport(
        @Param(value = "query", description = "Report query") String query,
        McpMeshTool<String> dataService) {

    if (dataService == null || !dataService.isAvailable()) {
        return "Data service unavailable";
    }
    return dataService.call("query", query);
}
```

## `McpMeshTool<T>` API Reference

The `McpMeshTool<T>` interface is the primary way to interact with remote capabilities. The type parameter `T` indicates the expected return type.

### call() - No Arguments

Invoke the remote tool with no parameters:

```java
McpMeshTool<String> dateService;
String today = dateService.call();
```

### call(Record) - Structured Parameters

Pass a Java record whose field names become parameter names:

```java
McpMeshTool<Integer> calculator;

record AddParams(int a, int b) {}
Integer sum = calculator.call(new AddParams(3, 5));  // sum = 8
```

### call(key, value, ...) - Varargs

Pass parameters as key-value pairs:

```java
McpMeshTool<String> greeting;
String result = greeting.call("name", "Alice", "language", "en");
```

### isAvailable()

Check if the remote capability is currently reachable:

```java
if (dateService != null && dateService.isAvailable()) {
    // Safe to call
}
```

### getEndpoint()

Get the remote endpoint URL:

```java
String url = dateService.getEndpoint();
// e.g., "http://localhost:9001"
```

### getCapability()

Get the capability name this proxy represents:

```java
String cap = dateService.getCapability();
// e.g., "date_service"
```

### API Summary

| Method            | Description                        | Return Type |
| ----------------- | ---------------------------------- | ----------- |
| `call()`          | No-arg invocation                  | `T`         |
| `call(record)`    | Call with record fields as params  | `T`         |
| `call(k, v, ...)` | Call with key-value pairs          | `T`         |
| `isAvailable()`   | Check provider reachability        | `boolean`   |
| `getEndpoint()`   | Remote agent endpoint URL          | `String`    |
| `getCapability()` | Capability name of this dependency | `String`    |

## Type-Safe Responses

The generic type parameter `T` on `McpMeshTool<T>` controls response deserialization. The SDK automatically converts the remote JSON response to the specified type.

```java
// Primitive types
McpMeshTool<Integer> calculator;
Integer sum = calculator.call(new AddParams(3, 5));

// String responses
McpMeshTool<String> dateService;
String today = dateService.call();

// Complex record types
McpMeshTool<Employee> employeeService;
Employee emp = employeeService.call("id", 42);
// Employee record is auto-deserialized from JSON

record Employee(int id, String name, String department) {}
```

## Graceful Degradation

Dependencies may be unavailable if the providing agent is down or not yet started. Always handle `null` and check availability:

```java
@MeshTool(capability = "agent_status",
          description = "Get status with dependency info",
          dependencies = @Selector(capability = "date_service"))
public AgentStatus getStatus(McpMeshTool<String> dateService) {
    boolean depAvailable = dateService != null && dateService.isAvailable();

    if (depAvailable) {
        String date = dateService.call();
        return new AgentStatus("operational", date);
    }
    return new AgentStatus("degraded", "date service unavailable");
}

record AgentStatus(String status, String info) {}
```

Or provide fallback values:

```java
@MeshTool(capability = "time_service",
          description = "Get current time",
          dependencies = @Selector(capability = "date_service"))
public TimeResponse getTime(McpMeshTool<String> dateService) {
    if (dateService != null && dateService.isAvailable()) {
        return new TimeResponse(dateService.call());
    }
    // Fallback to local time
    return new TimeResponse(java.time.LocalDateTime.now().toString());
}
```

## Auto-Rewiring

When topology changes (agents join/leave), the mesh:

1. Detects change via heartbeat response
2. Refreshes dependency proxies
3. Routes to new providers automatically

No code changes needed - happens transparently.

## Multiple Dependencies

A single tool can depend on multiple capabilities. Each dependency gets its own `McpMeshTool<T>` parameter:

```java
@MeshTool(capability = "add_via_mesh",
          description = "Add two numbers using remote calculator",
          tags = {"math", "cross-agent", "java"},
          dependencies = @Selector(capability = "add"))
public CalculationResult addViaMesh(
        @Param(value = "a", description = "First number") int a,
        @Param(value = "b", description = "Second number") int b,
        McpMeshTool<Integer> calculator) {

    Integer sum = calculator.call(new AddParams(a, b));
    return new CalculationResult("add", a, b, sum);
}

record AddParams(int a, int b) {}
record CalculationResult(String op, int a, int b, int result) {}
```

### LLM Injection

For `@MeshLlm` annotated tools, the LLM is injected as a `MeshLlmAgent` parameter:

```java
@MeshLlm(providerSelector = @Selector(capability = "llm"),
         maxIterations = 5, systemPrompt = "You are a helpful analyst.")
@MeshTool(capability = "analyze",
          description = "AI-powered analysis",
          tags = {"analysis", "llm", "java"})
public AnalysisResult analyze(
        @Param(value = "query", description = "Analysis query") String query,
        MeshLlmAgent llm) {

    return llm.request()
              .user(query)
              .generate(AnalysisResult.class);
}
```

## Complete Example

```java
package com.example.assistant;

import io.mcpmesh.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "assistant", version = "1.0.0",
           description = "Assistant with mesh dependencies", port = 9001)
@SpringBootApplication
public class AssistantAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(AssistantAgentApplication.class, args);
    }

    @MeshTool(capability = "smart_greeting",
              description = "Greet with current date from mesh",
              tags = {"greeting", "assistant", "java"},
              dependencies = @Selector(capability = "date_service"))
    public GreetingResponse smartGreet(
            @Param(value = "name", description = "The name to greet") String name,
            McpMeshTool<String> dateService) {

        if (dateService != null && dateService.isAvailable()) {
            String dateString = dateService.call();
            return new GreetingResponse(
                "Hello, " + name + "! Today is " + dateString);
        }
        return new GreetingResponse(
            "Hello, " + name + "! (date service unavailable)");
    }

    @MeshTool(capability = "agent_status",
              description = "Get agent status with dependency info",
              tags = {"status", "info", "java"},
              dependencies = @Selector(capability = "date_service"))
    public AgentStatus getStatus(McpMeshTool<String> dateService) {
        boolean available = dateService != null && dateService.isAvailable();
        String endpoint = available ? dateService.getEndpoint() : "N/A";
        String capability = available ? dateService.getCapability() : "N/A";

        return new AgentStatus("assistant", available, endpoint, capability);
    }

    record GreetingResponse(String message) {}
    record AgentStatus(String agent, boolean depAvailable,
                       String depEndpoint, String depCapability) {}
}
```

## See Also

- `meshctl man capabilities --java` - Declaring capabilities
- `meshctl man tags --java` - Tag-based selection
- `meshctl man decorators --java` - All Java annotations
