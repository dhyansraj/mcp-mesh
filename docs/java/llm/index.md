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

MCP Mesh provides first-class LLM support for Java/Spring Boot agents through the `@MeshLlm` annotation. LLM calls are routed through a mesh-registered **provider agent** (`@MeshLlmProvider`); consumers (`@MeshLlm`) never hold the API key.

```
User -> Consumer Agent -> Mesh -> LLM Provider Agent -> Vendor API
                                  (API key lives here only)
```

> **Tip**: Bootstrap a provider with
> `meshctl scaffold llm-provider --vendor claude --lang java --name claude-provider`
> and a consumer with
> `meshctl scaffold llm --vendor claude --lang java --name analyst-agent`.

## @MeshLlm Consumer

Use `providerSelector` to discover the LLM provider in the mesh:

```java
@MeshLlm(
    providerSelector = @Selector(capability = "llm", tags = {"+claude"}),
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

The provider agent (a separate Spring Boot process declared with
`@MeshLlmProvider`) holds the vendor API key; the consumer above never does.

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

| Provider                | Model Format                   |
| ----------------------- | ------------------------------ |
| Anthropic               | `anthropic/claude-sonnet-4-5`  |
| OpenAI                  | `openai/gpt-4o`                |
| Google AI Studio        | `gemini/gemini-2.5-flash`      |
| Google Vertex AI (IAM)  | `vertex_ai/gemini-2.5-flash`   |
| Mistral                 | `mistral/mistral-large-latest` |

## Vertex AI (Gemini via IAM)

The Java runtime supports Gemini via Google Cloud Vertex AI as an
alternative to AI Studio. Same model family, same `GeminiHandler`, same
HINT-mode prompt shaping for structured output with tools — only the
provider value, dependency, and auth config change.

### When to use Vertex AI vs AI Studio

| Use case                                              | Pick                                                                                  |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Quickstart / dev / lowest setup                       | AI Studio provider (`model = "gemini/gemini-2.5-flash"`, `GOOGLE_AI_GEMINI_API_KEY`)  |
| Production with IAM auth, GCP audit logs, VPC-SC      | Vertex AI provider (`model = "vertex_ai/gemini-2.5-flash"`, ADC)                      |
| Need Provisioned Throughput (no capacity 429s)        | Vertex AI provider                                                                    |
| Multi-tenant org-controlled billing                   | Vertex AI provider                                                                    |

### Setup

1. Add the Vertex AI Spring AI starter to your `pom.xml` (mesh's
   `mcp-mesh-spring-ai` does **not** pull it in by default — it's optional
   so non-Vertex users don't drag in `google-cloud-aiplatform`):

   ```xml
   <dependency>
     <groupId>org.springframework.ai</groupId>
     <artifactId>spring-ai-starter-model-vertex-ai-gemini</artifactId>
     <version>${spring-ai.version}</version>
   </dependency>
   ```

2. Configure project + location in `application.yml` (or via env vars
   through Spring Boot's relaxed binding):

   ```yaml
   spring:
     ai:
       vertex:
         ai:
           gemini:
             project-id: ${SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID:my-gcp-project}
             location:   ${SPRING_AI_VERTEX_AI_GEMINI_LOCATION:us-central1}
             chat:
               options:
                 model: gemini-2.5-flash
   ```

3. Configure GCP Application Default Credentials:

   ```bash
   gcloud auth application-default login
   # OR for CI/prod:
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
   ```

4. Run a Java provider with `@MeshLlmProvider`:

   ```java
   @MeshAgent(name = "gemini-provider", port = 9111)
   @MeshLlmProvider(
       capability = "llm",
       tags = {"llm", "gemini", "vertex"},
       model = "vertex_ai/gemini-2.5-flash"
   )
   @SpringBootApplication
   public class GeminiProviderApplication {
       public static void main(String[] args) {
           SpringApplication.run(GeminiProviderApplication.class, args);
       }
   }
   ```

   Consumers don't change — they keep their existing
   `@MeshLlm(providerSelector = @Selector(capability = "llm", tags = {"+gemini"}))`
   selector. The `vertex_ai/*` model prefix tells `SpringAiLlmProvider` to
   bind to the IAM-backed `vertexAiGeminiChatModel` bean.

### Switching backends

Migrate from AI Studio to Vertex AI by changing the provider agent's `model`
string and swapping the Spring AI starter dependency:

```java
// Provider — before:
@MeshLlmProvider(model = "gemini/gemini-2.5-flash", capability = "llm", tags = {"llm","gemini"})
// Provider — after:
@MeshLlmProvider(model = "vertex_ai/gemini-2.5-flash", capability = "llm", tags = {"llm","gemini","vertex"})
```

Swap the dependency in `pom.xml`
(`spring-ai-starter-model-google-genai` → `spring-ai-starter-model-vertex-ai-gemini`)
and replace `GOOGLE_AI_GEMINI_API_KEY` with ADC + the
`spring.ai.vertex.ai.gemini.*` properties shown above. Consumer agents are
unchanged.

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
