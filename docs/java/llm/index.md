<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/llm/index/">Python LLM Integration</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/llm/index/">TypeScript LLM Integration</a></span>
</div>

# LLM Integration (Java/Spring Boot)

> Building LLM-powered agents with @MeshLlm annotation

## Overview

MCP Mesh provides first-class LLM support for Java/Spring Boot agents through the `@MeshLlm` annotation. Two modes are available:

| Mode              | Annotation                          | API Key Location | Use Case                         |
| ----------------- | ----------------------------------- | ---------------- | -------------------------------- |
| **Direct**        | `@MeshLlm(provider = "claude")`     | Local agent      | Single agent, simpler setup      |
| **Mesh Delegate** | `@MeshLlm(providerSelector = @...)` | Provider agent   | Shared LLM, centralized key mgmt |

## Architecture

### Direct Mode

```
User -> Agent -> Spring AI -> Claude API (direct)
                 (local API key)
```

### Mesh Delegation Mode

```
User -> Agent -> Mesh -> LLM Provider Agent -> Claude API
                         (API key here only)
```

## Direct LLM (@MeshLlm with provider)

Use `provider = "claude"` or `provider = "openai"` for direct API calls. Requires the API key set locally.

```java
import io.mcpmesh.*;
import io.mcpmesh.types.MeshLlmAgent;

@MeshLlm(
    provider = "claude",
    maxIterations = 1,
    systemPrompt = "You are a helpful, friendly assistant. Keep responses concise.",
    maxTokens = 1024,
    temperature = 0.7
)
@MeshTool(
    capability = "chat",
    description = "Interactive chat with Claude",
    tags = {"chat", "llm", "java", "direct"}
)
public ChatResponse chat(
    @Param(value = "message", description = "User message") String message,
    MeshLlmAgent llm
) {
    if (llm != null && llm.isAvailable()) {
        String response = llm.generate(message);
        return new ChatResponse(message, response, "direct:claude");
    }
    return new ChatResponse(message, "LLM unavailable", "fallback");
}
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

## Mesh Delegation (@MeshLlm with providerSelector)

Use `providerSelector` to delegate LLM calls to a provider agent in the mesh. No local API key needed.

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm"),
    maxIterations = 5,
    systemPrompt = "classpath:prompts/analyst.ftl",
    contextParam = "ctx",
    filter = @Selector(tags = {"data", "tools"}),
    filterMode = FilterMode.ALL,
    maxTokens = 4096,
    temperature = 0.7
)
@MeshTool(
    capability = "analyze",
    description = "AI-powered data analysis",
    tags = {"analysis", "llm", "java"}
)
public AnalysisResult analyze(
    @Param(value = "ctx", description = "Analysis context") AnalysisContext ctx,
    MeshLlmAgent llm
) {
    if (llm == null || !llm.isAvailable()) {
        return fallbackAnalysis(ctx);
    }
    return llm.request()
        .user(ctx.query())
        .generate(AnalysisResult.class);
}
```

## Fluent Builder API

The `MeshLlmAgent` provides a fluent builder for clean, readable LLM calls:

### Simple Text Generation

```java
String response = llm.request()
    .user("What is the capital of France?")
    .temperature(0.7)
    .generate();
```

### Structured Output

Return a Java record or class by passing the type to `generate()`:

```java
public record AnalysisResult(
    String summary,
    List<String> insights,
    double confidence,
    String source
) {}

AnalysisResult result = llm.request()
    .user("Analyze Q4 sales trends")
    .maxTokens(4096)
    .temperature(0.7)
    .generate(AnalysisResult.class);
```

### With System Prompt Override

```java
String response = llm.request()
    .system("You are a code review expert.")
    .user("Review this function for bugs")
    .maxTokens(2048)
    .generate();
```

## Multi-Turn Conversations

Use `messages()` with `Message` helpers to pass conversation history:

```java
import io.mcpmesh.types.MeshLlmAgent.Message;

// Build history (typically loaded from Redis/database)
List<Message> history = new ArrayList<>();
history.add(Message.user("Hello, I'm interested in data analysis."));
history.add(Message.assistant("What kind of data are you working with?"));
history.add(Message.user("I have sales data from Q4 2024."));
history.add(Message.assistant("What insights are you looking for?"));

// Continue conversation with history
String response = llm.request()
    .system("You are a helpful assistant. Remember the conversation context.")
    .messages(history)
    .user("Show me the top trends")
    .maxTokens(2048)
    .temperature(0.7)
    .generate();
```

### Loading History from Database

```java
// Load from Redis/PostgreSQL as List<Map<String, String>>
List<Map<String, String>> rawHistory = redis.lrange("chat:" + sessionId, 0, -1);
List<Message> history = Message.fromMaps(rawHistory);

String response = llm.request()
    .messages(history)
    .user(currentMessage)
    .generate();
```

## Tool Filtering

Control which mesh tools the LLM can discover and call:

```java
// Filter by tags
filter = @Selector(tags = {"data", "tools"})

// Filter by capability
filter = @Selector(capability = "calculator")

// FilterMode controls selection
filterMode = FilterMode.ALL          // All tools matching filter
filterMode = FilterMode.BEST_MATCH   // One tool per capability (best tag match)
```

## System Prompts

### Inline String

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm"),
    systemPrompt = "You are a helpful assistant. Analyze the input and respond."
)
```

### Freemarker Template File

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm"),
    systemPrompt = "classpath:prompts/analyst.ftl",
    contextParam = "ctx"
)
```

Template file (`src/main/resources/prompts/analyst.ftl`):

```ftl
You are a data analyst assistant.

## Query
${ctx.query}

## Instructions
Analyze the data and provide structured insights.
```

The `contextParam` value maps to the parameter name in the tool method. Template variables are populated from that parameter's fields.

## @MeshLlmProvider - Zero-Code Provider

Create an LLM provider agent with zero implementation code:

```java
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlmProvider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MeshAgent(
    name = "claude-provider",
    version = "1.0.0",
    description = "Claude LLM provider for mesh",
    port = 9110
)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",
    capability = "llm",
    tags = {"llm", "claude", "anthropic", "provider"},
    version = "1.0.0"
)
@SpringBootApplication
public class ClaudeProviderApplication {
    public static void main(String[] args) {
        SpringApplication.run(ClaudeProviderApplication.class, args);
    }
    // No implementation needed - @MeshLlmProvider handles everything!
}
```

The provider automatically:

1. Creates a tool with `capability = "llm"`
2. Registers with the mesh registry
3. Handles incoming generate requests
4. Forwards to Spring AI ChatClient
5. Returns responses through the mesh

## Provider Pattern Benefits

- **Centralized API keys**: Only the provider agent needs the key
- **Rate limiting**: Apply limits at the provider level
- **Swap providers**: Switch LLM vendors without redeploying consumers
- **Shared access**: Multiple consumer agents share a single provider
- **Monitoring**: Centralized logging and cost tracking

## Supported Models

Uses LiteLLM model format in `@MeshLlmProvider`:

| Provider  | Model Format                   |
| --------- | ------------------------------ |
| Anthropic | `anthropic/claude-sonnet-4-5`  |
| OpenAI    | `openai/gpt-4o`                |
| Mistral   | `mistral/mistral-large-latest` |
| Google    | `gemini/gemini-pro`            |

## Complete Example

```java
// 1. Provider Agent (claude-provider, port 9110)
@MeshAgent(name = "claude-provider", port = 9110)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",
    capability = "llm",
    tags = {"llm", "claude", "provider"}
)
@SpringBootApplication
public class ProviderApp {
    public static void main(String[] args) {
        SpringApplication.run(ProviderApp.class, args);
    }
}

// 2. Consumer Agent (analyst, port 9002)
@MeshAgent(name = "analyst", port = 9002)
@SpringBootApplication
public class AnalystApp {
    public static void main(String[] args) {
        SpringApplication.run(AnalystApp.class, args);
    }

    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
        maxIterations = 5,
        systemPrompt = "You are a data analyst.",
        filter = @Selector(tags = {"data", "tools"}),
        filterMode = FilterMode.ALL
    )
    @MeshTool(
        capability = "analyze",
        description = "AI-powered analysis",
        tags = {"analysis", "llm"}
    )
    public AnalysisResult analyze(
        @Param(value = "query", description = "Analysis query") String query,
        MeshLlmAgent llm
    ) {
        return llm.request()
            .user(query)
            .maxTokens(4096)
            .generate(AnalysisResult.class);
    }

    public record AnalysisResult(
        String summary,
        List<String> insights,
        double confidence
    ) {}
}
```

## See Also

- `meshctl man decorators --java` - All annotations reference
- `meshctl man tags` - Tag matching for provider selection
- `meshctl man capabilities` - Capability discovery
