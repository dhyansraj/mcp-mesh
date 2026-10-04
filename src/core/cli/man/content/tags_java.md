# Tag Matching System (Java/Spring Boot)

> Smart service selection using tags with +/- operators

## Overview

Tags are metadata labels attached to capabilities that enable intelligent service selection. MCP Mesh supports "smart matching" with operators that express preferences and exclusions.

Tags are part of the **Capability Selector** syntax used throughout MCP Mesh. See `meshctl man capabilities --java` for the complete selector reference.

## Tag Operators (Consumer Side)

Use these operators when **selecting** capabilities (dependencies, providers, filters):

| Prefix | Meaning   | Example                                 |
| ------ | --------- | --------------------------------------- |
| (none) | Required  | `"api"` - must have this tag            |
| `+`    | Preferred | `"+fast"` - bonus if present            |
| `-`    | Excluded  | `"-deprecated"` - hard failure if found |

**Note:** Operators are for consumers only. When declaring tags on your tool, use plain strings without +/- prefixes.

## Declaring Tags (Provider Side)

```java
@MeshTool(capability = "weather_data",
          description = "Provides weather info",
          tags = {"weather", "current", "api", "free"})  // Plain strings
public WeatherResponse getWeather(
        @Param(value = "city", description = "City name") String city) {
    return new WeatherResponse(city, 72);
}

record WeatherResponse(String city, int temp) {}
```

## Using Tags in Dependencies

### Simple Tag Filter

```java
@MeshTool(capability = "my_capability",
          description = "Tool using weather data",
          dependencies = @Selector(capability = "weather_data",
                                    tags = {"api"}))
public String getInfo(McpMeshTool<String> weatherData) {
    if (weatherData != null && weatherData.isAvailable()) {
        return weatherData.call("city", "NYC");
    }
    return "Weather service unavailable";
}
```

### Smart Matching with Operators

```java
@MeshTool(capability = "smart_weather",
          description = "Smart weather lookup",
          dependencies = @Selector(
              capability = "weather_data",
              tags = {
                  "api",          // Required: must have "api" tag
                  "+accurate",    // Preferred: bonus if "accurate"
                  "+fast",        // Preferred: bonus if "fast"
                  "-deprecated"   // Excluded: fail if "deprecated"
              }))
public String smartWeather(McpMeshTool<String> weatherData) {
    if (weatherData != null && weatherData.isAvailable()) {
        return weatherData.call("city", "NYC");
    }
    return "No suitable weather service found";
}
```

## Matching Algorithm

1. **Filter**: Remove candidates with excluded tags (`-`)
2. **Require**: Keep only candidates with required tags (no prefix)
3. **Score**: Add points for preferred tags (`+`)
4. **Select**: Choose highest-scoring candidate

### Example

Available providers:

- Provider A: `["weather", "api", "accurate"]`
- Provider B: `["weather", "api", "fast", "deprecated"]`
- Provider C: `["weather", "api", "fast", "accurate"]`

Filter: `{"api", "+accurate", "+fast", "-deprecated"}`

Result:

1. Provider B eliminated (has `-deprecated`)
2. Remaining: A and C (both have required `api`)
3. Scores: A=1 (accurate), C=2 (accurate+fast)
4. Winner: Provider C

## Tag Naming Conventions

| Category    | Examples                       |
| ----------- | ------------------------------ |
| Type        | `api`, `service`, `provider`   |
| Quality     | `fast`, `accurate`, `reliable` |
| Status      | `beta`, `stable`, `deprecated` |
| Provider    | `openai`, `claude`, `local`    |
| Environment | `production`, `staging`, `dev` |

## Priority Scoring with Preferences

Stack multiple `+` tags to create priority ordering. The provider matching the most preferred tags wins.

```java
@MeshLlm(providerSelector = @Selector(
             capability = "llm",
             tags = {"+claude", "+anthropic", "+gpt"}),
         systemPrompt = "You are helpful.",
         maxIterations = 1)
@MeshTool(capability = "chat",
          description = "Chat with best available LLM",
          tags = {"chat", "llm", "java"})
public String chat(
        @Param(value = "message", description = "User message") String message,
        MeshLlmAgent llm) {
    return llm.generate(message);
}
```

| Provider | Its Tags                         | Matches             | Score  |
| -------- | -------------------------------- | ------------------- | ------ |
| Claude   | `["llm", "claude", "anthropic"]` | +claude, +anthropic | **+2** |
| GPT      | `["llm", "gpt", "openai"]`       | +gpt                | **+1** |
| Llama    | `["llm", "llama"]`               | (none)              | **+0** |

Result: Claude (+2) > GPT (+1) > Llama (+0)

## Tool Filtering in @MeshLlm

Filter which tools an LLM agent can access using the `filter` and `filterMode` attributes:

```java
@MeshLlm(providerSelector = @Selector(capability = "llm"),
         filter = @Selector(tags = {"executor", "tools"}),
         filterMode = FilterMode.ALL,
         systemPrompt = "You are a helpful assistant.",
         maxIterations = 5)
@MeshTool(capability = "assistant",
          description = "LLM-powered assistant",
          tags = {"assistant", "llm", "java"})
public String assist(
        @Param(value = "query", description = "User query") String query,
        MeshLlmAgent llm) {
    return llm.generate(query);
}
```

## Filter Modes

| Mode                    | Description                              |
| ----------------------- | ---------------------------------------- |
| `FilterMode.ALL`        | Include all tools matching any filter    |
| `FilterMode.BEST_MATCH` | One tool per capability (best tag match) |

## Tag OR Alternatives

Write `a|b` as one tag to require at least one of the alternatives:

```java
// Require "addition" AND ("python" OR "typescript")
dependencies = @Selector(capability = "math",
                          tags = {"addition", "python|typescript"})
```

Each `a|b` entry is one OR group, and a selector can carry several. The SDK
sends it to the registry as a nested array (`["addition", ["python", "typescript"]]`),
the same wire form Python and TypeScript use. Every `|` must separate two
non-empty alternatives: a tag such as `"python|"` or `"a||b"` fails the agent
at startup.

### Preferring One Alternative

The order of the alternatives does not matter: any provider that carries one
of them qualifies, and the highest-scoring provider wins. To prefer one
alternative, give it a `+`:

```java
// Prefer the python implementation, accept typescript
tags = {"addition", "+python|typescript"}
```

A `-` alternative never counts as a match. It only rejects providers that
carry the tag, so `"python|-legacy"` means `python` required and `legacy`
forbidden, and a group of only `-` alternatives can never match. Write
exclusions as separate tags (`"-legacy"`).

OR groups work in dependency selectors (`@MeshTool` dependencies,
`@MeshDependency` on `@MeshRoute`/`@MeshA2A`/`@MeshDependsOn`, `@MeshService`
view methods). In `@MeshLlm` `providerSelector` and `filter`, and in a tool's
own `tags`, a tag containing `|` is matched literally. Use `+` tags to rank
providers there.

## Complete Example

```java
package com.example.weather;

import io.mcpmesh.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "weather-consumer", version = "1.0.0",
           description = "Weather consumer with smart selection", port = 8080)
@SpringBootApplication
public class WeatherConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(WeatherConsumerApplication.class, args);
    }

    @MeshTool(capability = "forecast",
              description = "Get forecast using best available weather provider",
              tags = {"weather", "forecast", "java"},
              dependencies = @Selector(
                  capability = "weather_data",
                  tags = {
                      "api",          // Must have API access
                      "+accurate",    // Prefer accurate
                      "+fast",        // Prefer fast
                      "+premium",     // Prefer premium
                      "-deprecated",  // Never use deprecated
                      "-beta"         // Avoid beta services
                  }))
    public ForecastResponse getForecast(
            @Param(value = "city", description = "City name") String city,
            @Param(value = "days", description = "Forecast days") int days,
            McpMeshTool<WeatherData> weatherData) {

        if (weatherData == null || !weatherData.isAvailable()) {
            return new ForecastResponse("error",
                "No weather service available. Check mesh status with 'meshctl list'");
        }

        WeatherData data = weatherData.call("city", city, "days", days);
        return new ForecastResponse("ok", data.toString());
    }

    record ForecastResponse(String status, String data) {}
    record WeatherData(String city, int temp, String conditions) {}
}
```

## See Also

- `meshctl man capabilities --java` - Capabilities system
- `meshctl man dependency-injection --java` - How DI works
- `meshctl man decorators --java` - All Java annotations
