# LLM Provider Agent (Java)

A zero-code MCP Mesh LLM provider using `@MeshLlmProvider`.

## What This Example Shows

- `@MeshLlmProvider` - Zero-code LLM provider annotation
- Exposes `capability="llm"` to the mesh
- Other agents delegate LLM calls to this provider
- Centralized API key management

## How It Works

```
Consumer Agent                    Provider Agent (this)
(@MeshLlm)                        (@MeshLlmProvider)
    |                                   |
    +-- providerSelector: llm --------> +-- capability: llm
    |                                   |
    +-- generate("prompt") -----------> +-- receive request
    |                                   |
    |                                   +-- call Spring AI
    |                                   |
    |                                   +-- call Claude API
    |                                   |
    +<-- response ----------------------+
```

## Benefits of Provider Pattern

- **Centralized API key** - Only provider agent needs the API key
- **Rate limiting** - Control at provider level
- **Easy switching** - Swap LLM provider without redeploying consumers
- **Shared provider** - Multiple consumer agents share one provider
- **Monitoring** - Centralized logging and metrics

## Prerequisites

1. **Anthropic API Key:**

   ```bash
   export ANTHROPIC_API_KEY=your-key-here
   ```

2. Build the MCP Mesh Java SDK:
   ```bash
   cd src/runtime/java
   mvn install -DskipTests
   ```

## Running

### 1. Start the Registry

```bash
meshctl start --registry-only
```

### 2. Run the Provider Agent

```bash
cd examples/java/llm-provider-agent

# With Maven
ANTHROPIC_API_KEY=your-key mvn spring-boot:run

# Or build and run JAR
mvn package
ANTHROPIC_API_KEY=your-key java -jar target/llm-provider-agent-1.0.0-SNAPSHOT.jar
```

### 3. Verify Provider is Registered

```bash
# List agents
meshctl list
# Output: claude-provider  healthy  http://localhost:9110

# List tools
meshctl list -t
# Output: llm  Generate text with Claude
```

### 4. Test Directly

```bash
# Call the LLM capability directly
meshctl call llm '{"prompt": "Hello, how are you?"}'
```

### 5. Run a Consumer Agent

Start a consumer agent that uses mesh delegation:

```bash
cd examples/java/llm-mesh-agent
mvn spring-boot:run

# The consumer will automatically discover and use the provider
meshctl call analyze '{"ctx": {"query": "What is AI?"}}'
```

## Configuration

Override settings via environment variables:

| Variable                | Description       | Default                 |
| ----------------------- | ----------------- | ----------------------- |
| `ANTHROPIC_API_KEY`     | Anthropic API key | (required)              |
| `MCP_MESH_REGISTRY_URL` | Registry URL      | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port   | `9110`                  |
| `MCP_MESH_AGENT_NAME`   | Agent name        | `claude-provider`       |

## Code Structure

```
src/main/java/com/example/provider/
└── ClaudeProviderApplication.java   # Zero-code provider

src/main/resources/
└── application.yml                  # Spring AI + Mesh configuration

src/test/java/com/example/provider/
└── ClaudeProviderTest.java          # Annotation tests
```

## Key Concepts

### Zero-Code Provider

The entire provider is defined with annotations - no implementation needed:

```java
@MeshAgent(
    name = "claude-provider",
    version = "1.0.0",
    port = 9110
)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",
    capability = "llm",
    tags = {"llm", "claude", "anthropic", "provider"}
)
@SpringBootApplication
public class ClaudeProviderApplication {
    public static void main(String[] args) {
        SpringApplication.run(ClaudeProviderApplication.class, args);
    }
    // No implementation needed!
}
```

### Consumer Integration

Consumer agents use `providerSelector` to delegate to this provider:

```java
@MeshLlm(
    providerSelector = @Selector(
        capability = "llm",
        tags = {"+claude", "+anthropic"}
    ),
    maxIterations = 5
)
public Result analyze(Context ctx, MeshLlmAgent llm) {
    // This call is routed to the provider via mesh
    return llm.generate(prompt, Result.class);
}
```

### Provider Discovery

Consumers discover providers using capability and tag matching:

```java
// Provider registers with:
capability = "llm"
tags = ["llm", "claude", "anthropic", "provider"]

// Consumer requests:
@Selector(capability = "llm", tags = {"+claude"})
// Matches because provider has "claude" tag

// Consumer with different preference:
@Selector(capability = "llm", tags = {"+openai"})
// Would NOT match this provider (no "openai" tag)
```

## Multiple Providers

You can run multiple provider agents with different models:

```bash
# Claude provider
MCP_MESH_AGENT_NAME=claude-provider MCP_MESH_HTTP_PORT=9110 \
  ANTHROPIC_API_KEY=key mvn spring-boot:run

# (In another terminal) OpenAI provider (would need different app)
MCP_MESH_AGENT_NAME=openai-provider MCP_MESH_HTTP_PORT=9111 \
  OPENAI_API_KEY=key mvn spring-boot:run -Dspring.profiles.active=openai
```

Consumers can then select their preferred provider:

- `tags = {"+claude"}` - Prefer Claude
- `tags = {"+openai"}` - Prefer OpenAI
- `tags = {"llm"}` - Any LLM provider
