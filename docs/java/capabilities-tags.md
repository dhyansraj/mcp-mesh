<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/capabilities-tags/">Python Capabilities</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/capabilities-tags/">TypeScript Capabilities</a></span>
</div>

# Capabilities System (Java/Spring Boot)

> Named services that agents provide for discovery and dependency injection

## Overview

Capabilities are named services that agents register with the mesh. When an agent declares a capability, other agents can discover and use it through dependency injection. Multiple agents can provide the same capability with different implementations.

## Declaring Capabilities

Use `@MeshTool` to declare a capability on any method in your Spring Boot application:

```java
@MeshTool(capability = "weather_data",
          description = "Provides weather info",
          version = "1.0.0",
          tags = {"weather", "current", "api"})
public WeatherResponse getWeather(
        @Param(value = "city", description = "City name") String city) {
    return new WeatherResponse(city, 72, "sunny");
}

record WeatherResponse(String city, int temp, String conditions) {}
```

## Capability Selector Syntax

MCP Mesh uses the `@Selector` annotation for selecting capabilities. This same pattern appears in `dependencies`, `@MeshLlm` provider/filter, and `@MeshRoute`.

### Selector Fields

| Field        | Required | Description                                   |
| ------------ | -------- | --------------------------------------------- |
| `capability` | Yes\*    | Capability name to match                      |
| `tags`       | No       | Tag filters. Optional `+` (preferred) / `-` (excluded) operators |
| `version`    | No       | Semantic version constraint (e.g., `>=2.0.0`) |

\*When filtering by tags only (e.g., LLM tool filter), `capability` can be omitted.

### Selector Usage

**By capability name:**

```java
dependencies = @Selector(capability = "date_service")
```

**With tag filters:**

```java
dependencies = @Selector(capability = "weather_data",
                          tags = {"+fast", "-deprecated"})
```

**With version constraint:**

```java
dependencies = @Selector(capability = "api_client", version = ">=2.0.0")
```

### Where Selectors Are Used

| Context                   | Example                                                        |
| ------------------------- | -------------------------------------------------------------- |
| `@MeshTool` dependencies  | `dependencies = @Selector(capability = "svc")`                 |
| `@MeshLlm` provider       | `providerSelector = @Selector(capability = "llm")`             |
| `@MeshLlm` filter         | `filter = @Selector(tags = {"tools"})`                         |
| `@MeshRoute` dependencies | `dependencies = @Selector(capability = "api", tags = {"+v2"})` |

### Tag Operators

| Prefix | Meaning   | Example         |
| ------ | --------- | --------------- |
| (none) | Required  | `"api"`         |
| `+`    | Preferred | `"+fast"`       |
| `-`    | Excluded  | `"-deprecated"` |

## Multiple Capabilities on One Agent

A single agent class can declare multiple capabilities:

```java
@MeshAgent(name = "math-service", version = "1.0.0",
           description = "Math operations", port = 9000)
@SpringBootApplication
public class MathAgentApplication {

    @MeshTool(capability = "add",
              description = "Add two numbers",
              tags = {"math", "addition", "java"})
    public int add(@Param(value = "a", description = "First number") int a,
                   @Param(value = "b", description = "Second number") int b) {
        return a + b;
    }

    @MeshTool(capability = "multiply",
              description = "Multiply two numbers",
              tags = {"math", "multiplication", "java"})
    public int multiply(@Param(value = "a", description = "First number") int a,
                        @Param(value = "b", description = "Second number") int b) {
        return a * b;
    }
}
```

## Multiple Implementations

Multiple agents can provide the same capability:

```java
// Agent 1: Free weather provider
@MeshTool(capability = "weather_data",
          tags = {"weather", "openweather", "free"})
public WeatherResponse freeWeather(
        @Param(value = "city", description = "City name") String city) { /* ... */ }

// Agent 2: Premium weather provider
@MeshTool(capability = "weather_data",
          tags = {"weather", "premium", "accurate"})
public WeatherResponse premiumWeather(
        @Param(value = "city", description = "City name") String city) { /* ... */ }
```

Consumers select implementations using tag filters in `@Selector`:

```java
@MeshTool(capability = "forecast",
          description = "Get forecast using premium weather",
          dependencies = @Selector(capability = "weather_data",
                                    tags = {"+premium"}))
public ForecastResponse getForecast(
        @Param(value = "city", description = "City name") String city,
        McpMeshTool<WeatherResponse> weatherData) {
    if (weatherData != null && weatherData.isAvailable()) {
        WeatherResponse weather = weatherData.call("city", city);
        return new ForecastResponse(weather);
    }
    return new ForecastResponse("Weather service unavailable");
}
```

## Capability Resolution

When an agent requests a dependency, the registry resolves it by:

1. **Name matching**: Find agents providing the requested capability
2. **Tag filtering**: Apply tag constraints (if specified)
3. **Version constraints**: Check semantic version compatibility
4. **Load balancing**: Select from multiple matching providers

## Capability Naming Conventions

| Pattern         | Example         | Use Case         |
| --------------- | --------------- | ---------------- |
| `noun_noun`     | `weather_data`  | Data providers   |
| `verb_noun`     | `get_time`      | Action services  |
| `domain_action` | `auth_validate` | Domain-specific  |
| `service`       | `llm`           | Generic services |

## Versioning

Capabilities support semantic versioning:

```java
@MeshTool(capability = "api_client", version = "2.1.0",
          description = "API client v2", tags = {"api", "v2"})
public ApiResponse callApi(
        @Param(value = "endpoint", description = "API endpoint") String endpoint) {
    /* ... */
}
```

Consumers can specify version constraints:

```java
dependencies = @Selector(capability = "api_client", version = ">=2.0.0")
```

## See Also

- `meshctl man tags --java` - Tag matching system
- `meshctl man dependency-injection --java` - How DI works
- `meshctl man decorators --java` - All Java annotations
