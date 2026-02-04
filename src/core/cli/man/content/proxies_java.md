# Proxy System & Communication (Java/Spring Boot)

> Inter-agent communication via McpMeshTool proxies

## Overview

In Java/Spring Boot, `McpMeshTool<T>` is the proxy type for inter-agent communication. When you declare a dependency via `@Selector`, the mesh automatically injects a `McpMeshTool<T>` proxy that routes calls to the remote agent via MCP JSON-RPC.

## How Proxies Work

```
┌─────────────┐     Proxy Call      ┌─────────────┐
│   Agent A   │ ────────────────►   │   Agent B   │
│             │   MCP JSON-RPC      │             │
│  calc.call()│ ◄────────────────   │ add(a, b)   │
└─────────────┘     Response        └─────────────┘
```

1. Agent A calls `calculator.call(new AddParams(1, 2))`
2. Proxy serializes call to MCP JSON-RPC
3. HTTP POST to Agent B's `/mcp` endpoint
4. Agent B executes the `add` tool
5. Response deserialized into type `T` and returned

## Declaring Dependencies

Dependencies are declared via `@Selector` in `@MeshTool` and injected as method parameters:

```java
@MeshTool(
    capability = "smart_greeting",
    dependencies = @Selector(capability = "date_service")
)
public String smartGreet(
    @Param(value = "name", description = "Name") String name,
    McpMeshTool<String> dateService
) {
    if (dateService != null && dateService.isAvailable()) {
        String date = dateService.call();
        return "Hello, " + name + "! Today is " + date;
    }
    return "Hello, " + name + "!";
}
```

## McpMeshTool<T> API Reference

### call() - No Parameters

Call the remote tool with no arguments:

```java
McpMeshTool<String> dateService;

String today = dateService.call();
```

### call(record) - Record-Based Parameters

Use a Java record where field names map to MCP parameter names:

```java
record AddParams(int a, int b) {}

McpMeshTool<Integer> calculator;

Integer sum = calculator.call(new AddParams(3, 4));  // sum = 7
```

### call("key", value, ...) - Varargs Parameters

For simple parameter passing without defining a record:

```java
McpMeshTool<Employee> employeeService;

Employee emp = employeeService.call("id", 42);
```

Multiple key-value pairs:

```java
String result = service.call("city", "London", "units", "metric");
```

### isAvailable() - Check Reachability

Returns `true` if the remote agent is registered and reachable:

```java
if (dateService != null && dateService.isAvailable()) {
    // Safe to call
    String date = dateService.call();
}
```

### getEndpoint() - Remote URL

Get the HTTP endpoint of the remote agent:

```java
String url = dateService.getEndpoint();
// e.g., "http://localhost:9001"
```

### getCapability() - Capability Name

Get the capability name this proxy resolves to:

```java
String cap = dateService.getCapability();
// e.g., "date_service"
```

## Type-Safe Responses

The type parameter `T` in `McpMeshTool<T>` controls automatic deserialization:

### Primitive Types

```java
McpMeshTool<Integer> calculator;
Integer result = calculator.call(new AddParams(1, 2));

McpMeshTool<String> dateService;
String date = dateService.call();
```

### Complex Types (Records)

```java
public record Employee(
    int id,
    String firstName,
    String lastName,
    String department,
    double salary
) {}

McpMeshTool<Employee> employeeService;
Employee emp = employeeService.call("id", 42);
// emp.firstName() -> "Alice"
// emp.department() -> "Engineering"
```

The SDK automatically deserializes the remote agent's JSON response into the specified type. No manual parsing needed.

## Proxy Lifecycle

1. **Created on registration**: When the agent registers with the registry, proxies are created for resolved dependencies
2. **Updated on topology change**: When agents join or leave, the registry notifies via `202` heartbeat response, and proxies are refreshed
3. **Null if unavailable**: If no provider matches the dependency selector, the proxy parameter is `null`

Always check for `null` before calling:

```java
if (dateService != null && dateService.isAvailable()) {
    return dateService.call();
}
return "Fallback value";
```

## Cross-Language Calls

McpMeshTool proxies work across languages. A Java agent can call Python or TypeScript agents and vice versa:

```java
// Java agent calling a TypeScript calculator
@MeshTool(
    capability = "add_via_mesh",
    description = "Add via remote calculator (cross-agent)",
    dependencies = @Selector(capability = "add")
)
public CalculationResult addViaMesh(
    @Param(value = "a", description = "First number") int a,
    @Param(value = "b", description = "Second number") int b,
    McpMeshTool<Integer> calculator
) {
    Integer sum = calculator.call(new AddParams(a, b));
    return new CalculationResult(a, b, sum, calculator.getEndpoint());
}

record AddParams(int a, int b) {}
record CalculationResult(int a, int b, int result, String remoteEndpoint) {}
```

All agents speak the same MCP JSON-RPC protocol, so language is transparent.

## Error Handling

```java
@MeshTool(
    capability = "resilient_tool",
    dependencies = @Selector(capability = "helper")
)
public String resilientTool(McpMeshTool<String> helper) {
    if (helper == null) {
        return "Service unavailable";
    }

    try {
        return helper.call();
    } catch (Exception e) {
        return "Error: " + e.getMessage();
    }
}
```

## Direct Communication

Agents communicate directly with no proxy server:

- Registry provides endpoint information
- Agents call each other via HTTP
- Minimal latency (no intermediary)
- Continues working if registry is down

## See Also

- `meshctl man dependency-injection --java` - DI overview
- `meshctl man health --java` - Auto-rewiring on failure
- `meshctl man testing --java` - Testing agent communication
