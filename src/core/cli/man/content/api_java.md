# API Integration (Java/Spring Boot)

> Add mesh capabilities to your Spring Boot REST controllers with @MeshRoute

## Why Use This

- You have a Spring Boot app (or are building one) and want your controllers to call mesh agent capabilities (LLMs, data services, etc.)
- `@MeshRoute` + `@MeshDependency` gives you automatic dependency injection -- declare what you need, mesh provides it
- Your API registers as a consumer (Type: API) -- no MCP protocol, no `@MeshAgent` annotation needed
- Dependencies auto-rewire when agents come and go

## Install

Add to your `pom.xml`:

```xml
<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-spring-boot-starter</artifactId>
    <version>${mcp-mesh.version}</version>
</dependency>
<dependency>
    <groupId>io.mcp-mesh</groupId>
    <artifactId>mcp-mesh-sdk</artifactId>
    <version>${mcp-mesh.version}</version>
</dependency>
```

## Quick Start (Add to Existing App)

**Before** -- a normal Spring Boot endpoint:

```java
@GetMapping("/greet")
public ResponseEntity<Map<String, Object>> greet(@RequestParam String name) {
    // How do I call the greeting agent from here?
    return ResponseEntity.ok(Map.of("message", "..."));
}
```

**After** -- same endpoint with mesh dependency injection:

```java
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;

@GetMapping("/greet")
@MeshRoute(dependencies = @MeshDependency(capability = "greeting"))
public ResponseEntity<Map<String, Object>> greet(
        @RequestParam String name,
        McpMeshTool<Map<String, Object>> greeting) {

    Map<String, Object> result = greeting.call(Map.of("name", name));
    return ResponseEntity.ok(Map.of("source", "mesh-agent", "result", result));
}
```

The `McpMeshTool` is injected by parameter name matching the capability. Call `.call()` with your arguments -- mesh handles routing to the actual agent.

## Consumer-Only Mode

No `@MeshAgent` annotation needed. Just use `@SpringBootApplication` with `@MeshRoute` on your controller methods:

```java
@SpringBootApplication
public class MyApiApplication {
    public static void main(String[] args) {
        SpringApplication.run(MyApiApplication.class, args);
    }
}
```

Configure `application.yml`:

```yaml
server:
  port: 8080

mesh:
  registry:
    url: http://localhost:8000
```

That is all. The framework detects `@MeshRoute` usage and starts in consumer-only mode automatically.

## Dependency Declaration

### Simple (by capability name)

```java
@GetMapping("/data")
@MeshRoute(dependencies = @MeshDependency(capability = "user_service"))
public ResponseEntity<?> getData(McpMeshTool<Map<String, Object>> user_service) {
    Map<String, Object> result = user_service.call(Map.of("id", 42));
    return ResponseEntity.ok(result);
}
```

### With @MeshInject (explicit binding)

When the parameter name does not match the capability, use `@MeshInject`:

```java
@GetMapping("/employee")
@MeshRoute(dependencies = @MeshDependency(capability = "get_employee"))
public ResponseEntity<?> getEmployee(
        @RequestParam int id,
        @MeshInject("get_employee") McpMeshTool<Employee> employeeTool) {

    Employee employee = employeeTool.call(Map.of("id", id));
    return ResponseEntity.ok(employee);
}
```

## Typed Deserialization

Use `McpMeshTool<T>` generics to get automatic JSON-to-record conversion:

```java
record Employee(int id, String firstName, String lastName, String department, double salary) {}

@GetMapping("/employee")
@MeshRoute(dependencies = @MeshDependency(capability = "get_employee"))
public ResponseEntity<?> getEmployee(
        @RequestParam int id,
        @MeshInject("get_employee") McpMeshTool<Employee> employeeTool) {

    // Response is deserialized directly into an Employee record
    Employee employee = employeeTool.call(Map.of("id", id));
    return ResponseEntity.ok(Map.of(
        "result", employee,
        "type", employee.getClass().getSimpleName()
    ));
}
```

## Running

```bash
# 1. Start the mesh registry
meshctl start --registry-only

# 2. Start your Spring Boot app (not through meshctl)
cd your-app
mvn spring-boot:run
```

**Note**: Spring Boot API consumers are NOT started with `meshctl start` -- run them your normal way. The registry must be running so `@MeshRoute` can resolve dependencies.

## Graceful Degradation

Use `failOnMissingDependency = false` to allow requests when agents are unavailable:

```java
@GetMapping("/greet-fallback")
@MeshRoute(
    dependencies = @MeshDependency(capability = "greeting"),
    failOnMissingDependency = false
)
public ResponseEntity<?> greetWithFallback(
        @RequestParam(defaultValue = "World") String name,
        McpMeshTool<Map<String, Object>> greeting) {

    if (greeting != null && greeting.isAvailable()) {
        Map<String, Object> result = greeting.call(Map.of("name", name));
        return ResponseEntity.ok(Map.of("source", "mesh-agent", "result", result));
    } else {
        return ResponseEntity.ok(Map.of(
            "source", "local-fallback",
            "result", Map.of("message", "Hello, " + name + "! (from fallback)")
        ));
    }
}
```

Without this flag, a missing dependency returns `503 Service Unavailable` automatically.

## How It Works

1. Spring Boot starts and detects `@MeshRoute` annotations (no `@MeshAgent` needed)
2. Connects to the mesh registry in consumer-only mode
3. At request time, resolves dependencies and injects `McpMeshTool` proxies
4. If an agent goes down, mesh auto-rewires to an available replacement

## See Also

- `meshctl man decorators` - All mesh annotations
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration
