# MCP Mesh Annotations (Java/Spring Boot)

> Core annotations for building distributed agent systems

## Overview

MCP Mesh provides annotations that transform regular Spring Boot methods into mesh-aware distributed services. These annotations handle registration, dependency injection, and communication automatically.

| Annotation         | Purpose                                   |
| ------------------ | ----------------------------------------- |
| `@MeshAgent`       | Agent configuration (name, version, port) |
| `@MeshTool`        | Register capability with DI               |
| `@Param`           | Document tool parameters                  |
| `@Selector`        | Capability/tag selection for dependencies |
| `@MeshLlm`         | Enable LLM-powered tools                  |
| `@MeshLlmProvider` | Create zero-code LLM provider             |
| `@MeshRoute`       | REST endpoint with mesh DI                |

## @MeshAgent

Configures the agent identity. Applied to your `@SpringBootApplication` class.

```java
@MeshAgent(
    name = "my-service",          // Required: unique agent identifier
    version = "1.0.0",            // Semantic version
    description = "Service desc", // Human-readable description
    port = 9000                   // HTTP server port
)
@SpringBootApplication
public class MyAgentApplication {
    public static void main(String[] args) {
        SpringApplication.run(MyAgentApplication.class, args);
    }
}
```

| Attribute     | Required | Default   | Description                |
| ------------- | -------- | --------- | -------------------------- |
| `name`        | Yes      |           | Unique agent identifier    |
| `version`     | No       | `"1.0.0"` | Semantic version           |
| `description` | No       | `""`      | Human-readable description |
| `port`        | No       | `8080`    | HTTP server port           |

## @MeshTool

Registers a method as a mesh capability with dependency injection.

```java
@MeshTool(
    capability = "greeting",              // Capability name for discovery
    description = "Greets users",         // Human-readable description
    version = "1.0.0",                    // Capability version
    tags = {"greeting", "utility"},       // Tags for filtering
    dependencies = @Selector(             // Required capabilities
        capability = "date_service")
)
public GreetingResponse greet(
        @Param(value = "name", description = "The name") String name,
        McpMeshTool<String> dateService) {       // Injected dependency
    if (dateService != null && dateService.isAvailable()) {
        String today = dateService.call();
        return new GreetingResponse("Hello " + name + "! Today is " + today);
    }
    return new GreetingResponse("Hello " + name + "!");
}
```

| Attribute      | Required | Default | Description                   |
| -------------- | -------- | ------- | ----------------------------- |
| `capability`   | Yes      |         | Capability name for discovery |
| `description`  | No       | `""`    | Human-readable description    |
| `version`      | No       | `""`    | Capability version            |
| `tags`         | No       | `{}`    | Tags for filtering            |
| `dependencies` | No       |         | `@Selector` for required caps |

**Note**: Dependencies are injected as `McpMeshTool<T>` parameters on the method. They may be `null` if unavailable.

## @Param

Documents tool parameters. Applied to method parameters.

```java
@MeshTool(capability = "search", description = "Search documents")
public SearchResult search(
        @Param(value = "query", description = "Search query") String query,
        @Param(value = "limit", description = "Max results") int limit) {
    /* ... */
}
```

| Attribute     | Required | Description                |
| ------------- | -------- | -------------------------- |
| `value`       | Yes      | Parameter name             |
| `description` | No       | Human-readable description |

## @Selector

Specifies capability and tag selection for dependencies, LLM providers, and filters.

```java
// By capability name
@Selector(capability = "date_service")

// With tag filters
@Selector(capability = "weather_data", tags = {"+fast", "-deprecated"})

// With version constraint
@Selector(capability = "api_client", version = ">=2.0.0")

// Tags only (for LLM tool filtering)
@Selector(tags = {"data", "tools"})
```

| Attribute    | Required | Description                    |
| ------------ | -------- | ------------------------------ |
| `capability` | No\*     | Capability name to match       |
| `tags`       | No       | Tag filters with +/- operators |
| `version`    | No       | Semantic version constraint    |

\*Required for dependencies; optional for LLM tool filters.

## @MeshLlm

Enables LLM-powered tools. Applied alongside `@MeshTool` on the method.

### Via Mesh (providerSelector)

Route LLM requests through a mesh provider agent:

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm"),  // Find LLM via mesh
    maxIterations = 5,                                  // Max agentic loops
    systemPrompt = "classpath:prompts/analyst.ftl",     // FreeMarker template
    contextParam = "ctx",                               // Parameter for context
    filter = @Selector(tags = {"data", "tools"}),       // Tool filter
    filterMode = FilterMode.ALL,                        // Filter mode
    maxTokens = 4096,                                   // Max output tokens
    temperature = 0.7                                   // Sampling temperature
)
@MeshTool(capability = "analyze",
          description = "AI-powered analysis",
          tags = {"analysis", "llm", "java"})
public AnalysisResult analyze(
        @Param(value = "ctx", description = "Analysis context") AnalysisContext ctx,
        MeshLlmAgent llm) {
    return llm.request()
              .user(ctx.query())
              .maxTokens(4096)
              .temperature(0.7)
              .generate(AnalysisResult.class);
}
```

### Direct Provider (provider)

Use a specific LLM provider by name:

```java
@MeshLlm(
    provider = "claude",                    // Direct provider name
    maxIterations = 1,                      // Single generation
    systemPrompt = "You are a helpful assistant.",
    maxTokens = 1024,
    temperature = 0.7
)
@MeshTool(capability = "chat",
          description = "Chat with Claude",
          tags = {"chat", "llm", "java", "direct"})
public ChatResponse chat(
        @Param(value = "message", description = "User message") String message,
        MeshLlmAgent llm) {
    if (llm != null && llm.isAvailable()) {
        String response = llm.generate(message);
        return new ChatResponse(response);
    }
    return new ChatResponse("LLM unavailable");
}
```

| Attribute          | Required | Default | Description                          |
| ------------------ | -------- | ------- | ------------------------------------ |
| `provider`         | No\*     |         | Direct provider name                 |
| `providerSelector` | No\*     |         | `@Selector` for mesh LLM discovery   |
| `maxIterations`    | No       | `1`     | Max agentic loop iterations          |
| `systemPrompt`     | No       | `""`    | System prompt or template path       |
| `contextParam`     | No       | `""`    | Parameter name for template context  |
| `filter`           | No       |         | `@Selector` for tool filtering       |
| `filterMode`       | No       | `ALL`   | `FilterMode.ALL` or `BEST_MATCH`     |
| `maxTokens`        | No       | `0`     | Max output tokens (0 = default)      |
| `temperature`      | No       | `0.0`   | Sampling temperature (0.0 = default) |

\*Specify either `provider` (direct) or `providerSelector` (mesh discovery), not both.

### MeshLlmAgent API

```java
// Simple text generation
String response = llm.generate(message);

// Builder pattern with structured output
AnalysisResult result = llm.request()
    .system("Custom system prompt")
    .user("Analyze this data")
    .maxTokens(4096)
    .temperature(0.7)
    .generate(AnalysisResult.class);

// With message history
String response = llm.request()
    .messages(conversationHistory)
    .user("Follow-up question")
    .generate();

// Check availability
if (llm != null && llm.isAvailable()) { /* ... */ }

// Get generation metadata
llm.request().lastMeta();
```

## @MeshLlmProvider

Creates a zero-code LLM provider. No implementation needed - the annotation handles everything.

```java
@MeshAgent(name = "claude-provider", version = "1.0.0",
           description = "Claude LLM provider for mesh", port = 9110)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",            // LiteLLM model string
    capability = "llm",                                // Capability name
    tags = {"llm", "claude", "anthropic", "provider"}, // Discovery tags
    version = "1.0.0"                                  // Provider version
)
@SpringBootApplication
public class ClaudeProviderApplication {
    public static void main(String[] args) {
        SpringApplication.run(ClaudeProviderApplication.class, args);
    }
    // No implementation needed - annotation handles everything
}
```

| Attribute    | Required | Default | Description          |
| ------------ | -------- | ------- | -------------------- |
| `model`      | Yes      |         | LiteLLM model string |
| `capability` | Yes      |         | Capability name      |
| `tags`       | No       | `{}`    | Discovery tags       |
| `version`    | No       | `""`    | Provider version     |

## @MeshRoute

Enables mesh dependency injection in REST endpoint handlers.

```java
@MeshRoute(dependencies = @Selector(capability = "avatar_chat"))
@PostMapping("/chat")
public ResponseEntity<ChatResponse> chat(
        @RequestBody ChatRequest request,
        McpMeshTool<String> avatarChat) {
    if (avatarChat == null || !avatarChat.isAvailable()) {
        return ResponseEntity.status(503)
            .body(new ChatResponse("Service unavailable"));
    }
    String result = avatarChat.call("message", request.message());
    return ResponseEntity.ok(new ChatResponse(result));
}
```

## Environment Variable Overrides

All configuration can be overridden via environment variables:

```bash
export MCP_MESH_AGENT_NAME=custom-name
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_NAMESPACE=production
export MCP_MESH_REGISTRY_URL=http://registry:8000
```

## Complete Example

```java
package com.example.calculator;

import io.mcpmesh.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(name = "calculator", version = "1.0.0",
           description = "Calculator with logging", port = 9000)
@SpringBootApplication
public class CalculatorApplication {

    public static void main(String[] args) {
        SpringApplication.run(CalculatorApplication.class, args);
    }

    // Basic tool - no dependencies
    @MeshTool(capability = "add",
              description = "Add two numbers",
              tags = {"math", "calculator", "java"})
    public int add(@Param(value = "a", description = "First number") int a,
                   @Param(value = "b", description = "Second number") int b) {
        return a + b;
    }

    // Tool with dependency
    @MeshTool(capability = "calculator_logged",
              description = "Calculate with audit logging",
              tags = {"math", "calculator", "audit", "java"},
              dependencies = @Selector(capability = "audit_log"))
    public CalculationResult calculateWithLogging(
            @Param(value = "operation", description = "Operation") String operation,
            @Param(value = "a", description = "First number") int a,
            @Param(value = "b", description = "Second number") int b,
            McpMeshTool<String> auditLog) {

        int result = operation.equals("add") ? a + b : a - b;

        if (auditLog != null && auditLog.isAvailable()) {
            auditLog.call("action", "calculation",
                          "operation", operation, "result", result);
        }

        return new CalculationResult(operation, a, b, result);
    }

    record CalculationResult(String operation, int a, int b, int result) {}
}
```

## See Also

- `meshctl man dependency-injection --java` - DI details
- `meshctl man capabilities --java` - Capabilities system
- `meshctl man tags --java` - Tag matching system
