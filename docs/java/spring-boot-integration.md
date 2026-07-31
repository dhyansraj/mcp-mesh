# Spring Boot Integration

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../python/fastapi-integration/">Python FastAPI Integration</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../typescript/express-integration/">TypeScript Express Integration</a></span>
</div>

> Use mesh dependency injection in Spring Boot REST controllers with `@MeshRoute`

## Overview

MCP Mesh provides the `@MeshRoute` annotation for Spring Boot REST controllers that need to consume mesh capabilities. This enables traditional REST APIs to leverage the mesh service layer without being full MCP agents themselves.

**Important**: This is for integrating MCP Mesh into your EXISTING Spring Boot app. To create a new MCP agent, use `meshctl scaffold --lang java` instead.

## Installation

```xml
<dependencies>
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>3.3.2</version>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
</dependencies>
```

## Two Architectures

| Pattern              | Annotation                 | Use Case                              |
| -------------------- | -------------------------- | ------------------------------------- |
| MCP Agent            | `@MeshTool` + `@MeshAgent` | Service that _provides_ capabilities  |
| Spring Boot REST API | `@MeshRoute`               | REST API that _consumes_ capabilities |

```
[Frontend] -> [Spring Boot REST API] -> [MCP Mesh] -> [Agents]
                      ^
                @MeshRoute
```

## @MeshRoute Annotation

Apply `@MeshRoute` to a `@RestController` method to declare mesh dependencies. Dependencies are injected as typed `McpMeshTool<T>` parameters.

### Positional Pairing

The Nth `@MeshDependency` binds to the Nth `McpMeshTool` parameter, in signature order. Parameter names are never consulted, and business parameters (`@RequestParam`, `@RequestBody`, ...) take no part in the pairing:

```java
@GetMapping("/greet")
@MeshRoute(
    dependencies = @MeshDependency(capability = "greeting"),
    description = "Greet a user via the greeter mesh agent"
)
public ResponseEntity<Map<String, Object>> greet(
        @RequestParam(defaultValue = "World") String name,
        McpMeshTool<Map<String, Object>> greeting) {  // dependencies[0]

    Map<String, Object> result = greeting.call(Map.of("name", name));

    return ResponseEntity.ok(Map.of(
        "source", "mesh-agent",
        "result", result,
        "timestamp", LocalDateTime.now().toString()
    ));
}
```

With several dependencies, declaration order is the binding — name the parameters however reads best:

```java
@PostMapping("/process")
@MeshRoute(
    dependencies = {
        @MeshDependency(capability = "greeting"),
        @MeshDependency(capability = "agent_info")
    },
    description = "Process data using multiple mesh agents"
)
public ResponseEntity<Map<String, Object>> process(
        @RequestBody Map<String, Object> input,
        McpMeshTool<Map<String, Object>> greeter,    // dependencies[0] - greeting
        McpMeshTool<Map<String, Object>> infoTool) { // dependencies[1] - agent_info

    Map<String, Object> greetingResult = greeter.call(Map.of("name", input.get("name")));
    Map<String, Object> info = infoTool.call();

    return ResponseEntity.ok(Map.of(
        "greeting", greetingResult,
        "agentInfo", info
    ));
}
```

### @MeshInject asserts the position

`@MeshInject` does not select a dependency — it asserts the one position already assigns, and the application fails to start if the two disagree. It is optional; add it when you want the pairing pinned against a future reorder of either end:

```java
public ResponseEntity<Map<String, Object>> process(
        @RequestBody Map<String, Object> input,
        @MeshInject("greeting") McpMeshTool<Map<String, Object>> greeter,
        @MeshInject("agent_info") McpMeshTool<Map<String, Object>> infoTool) { ... }
```

!!! warning "Changed in 3.4.0"

    `@MeshRoute` used to bind **by name** — by the `@MeshInject` value, falling back to the Java parameter name. It now binds by position, like `@MeshTool` and like every Python and TypeScript site. See [Migrating to positional DI](../migration/3.4-positional-di.md) before upgrading a controller that declares more than one dependency.

## Optional Dependencies

By default, `@MeshRoute` returns 503 if a dependency is unavailable. Set `failOnMissingDependency = false` for graceful fallback:

```java
@GetMapping("/optional-greet")
@MeshRoute(
    dependencies = @MeshDependency(capability = "greeting"),
    failOnMissingDependency = false,
    description = "Greeting with fallback if agent unavailable"
)
public ResponseEntity<Map<String, Object>> greetWithFallback(
        @RequestParam(defaultValue = "World") String name,
        McpMeshTool<Map<String, Object>> greeting) {

    if (greeting != null && greeting.isAvailable()) {
        Map<String, Object> result = greeting.call(Map.of("name", name));
        return ResponseEntity.ok(Map.of("source", "mesh-agent", "result", result));
    }

    // Fallback when mesh agent is unavailable
    return ResponseEntity.ok(Map.of(
        "source", "local-fallback",
        "result", Map.of("message", "Hello, " + name + "! (from fallback)")
    ));
}
```

## Request Attribute Access

For more control, use `MeshRouteUtils` to access dependencies from the request:

```java
@GetMapping("/greet-alt")
@MeshRoute(
    dependencies = @MeshDependency(capability = "greeting"),
    description = "Alternative greeting using request attributes"
)
public ResponseEntity<Map<String, Object>> greetAlt(
        @RequestParam(defaultValue = "World") String name,
        HttpServletRequest request) {

    McpMeshTool<Map<String, Object>> greeterTool = MeshRouteUtils.getDependency(request, "greeting");

    if (greeterTool == null || !greeterTool.isAvailable()) {
        return ResponseEntity.status(503)
            .body(Map.of("error", "Greeter service not available"));
    }

    Map<String, Object> result = greeterTool.call(Map.of("name", name));

    return ResponseEntity.ok(Map.of("source", "mesh-agent", "result", result));
}
```

## Complete Example

```java
package com.example.api;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.Map;

@SpringBootApplication
@MeshAgent(name = "rest-api-consumer", version = "1.0.0")
public class RestApiConsumerApplication {
    public static void main(String[] args) {
        SpringApplication.run(RestApiConsumerApplication.class, args);
    }
}

@RestController
@RequestMapping("/api")
class ApiController {

    @GetMapping("/greet")
    @MeshRoute(
        dependencies = @MeshDependency(capability = "greeting"),
        description = "Greet via mesh agent"
    )
    public ResponseEntity<Map<String, Object>> greet(
            @RequestParam(defaultValue = "World") String name,
            McpMeshTool<Map<String, Object>> greeting) {

        Map<String, Object> result = greeting.call(Map.of("name", name));

        return ResponseEntity.ok(Map.of(
            "result", result,
            "timestamp", LocalDateTime.now().toString()
        ));
    }
}
```

## Running Your Spring Boot App

```bash
# 1. Start the registry and a provider agent
meshctl start --registry-only -d
meshctl start examples/java/basic-tool-agent -d

# 2. Start the REST API consumer
meshctl start examples/java/rest-api-consumer

# 3. Call the REST endpoint
curl http://localhost:8080/api/greet?name=World
```

The REST API will:

1. Connect to the mesh registry on startup
2. Resolve dependencies declared in `@MeshRoute`
3. Inject `McpMeshTool` proxies into controller methods
4. Re-resolve on topology changes (auto-rewiring)

## Key Differences from @MeshTool

| Aspect                | @MeshTool    | @MeshRoute                      |
| --------------------- | ------------ | ------------------------------- |
| Registers with mesh   | Yes          | Yes (as Type API)               |
| Provides capabilities | Yes          | No                              |
| Consumes capabilities | Yes          | Yes                             |
| Has heartbeat         | Yes          | Yes (for dependency resolution) |
| Protocol              | MCP JSON-RPC | REST/HTTP                       |
| Use case              | Microservice | API Gateway/Backend             |

## When to Use @MeshRoute

- Building a REST API that fronts mesh services
- API gateway pattern
- Backend-for-Frontend (BFF) services
- Adding mesh capabilities to existing Spring Boot apps
- When you need traditional HTTP semantics (REST, OpenAPI docs)

## When to Use @MeshTool Instead

- Building reusable mesh capabilities
- Service-to-service communication
- LLM tool providers
- When other agents need to discover and call your service

## See Also

- [Annotations Reference](./annotations.md) - All Java mesh annotations
- [Dependency Injection](./dependency-injection.md) - How DI works in Java
- `meshctl man dependency-injection --java` - DI details
- `meshctl man fastapi` - Python/FastAPI equivalent
- `meshctl man express` - TypeScript/Express equivalent
