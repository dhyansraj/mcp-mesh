# LLM Mesh Agent (Java)

An MCP Mesh agent demonstrating `@MeshLlm` with mesh delegation for LLM calls.

## What This Example Shows

- `@MeshLlm(providerSelector = ...)` - Delegate LLM calls to mesh provider
- `MeshLlmAgent` injection - LLM proxy automatically injected
- Tool filtering with `@Selector` - Discover tools from mesh based on tags
- Agentic loop - LLM calls tools, gets results, continues reasoning
- Freemarker templates - System prompts with context injection
- Structured output - Parse LLM responses to Java records

## Architecture

```
User Request
     |
     v
AnalystAgent (@MeshLlm)
     |
     +-- discovers tools from mesh (tag filter: "data", "tools")
     |
     +-- calls LLM Provider via mesh (providerSelector)
     |        |
     |        +-- LLM decides to call tools
     |        |
     |        +-- AnalystAgent executes tool calls via mesh
     |        |
     |        +-- Results returned to LLM
     |        |
     |        +-- LLM generates final response
     |
     v
Structured Result (AnalysisResult record)
```

## Prerequisites

1. Build the MCP Mesh Java SDK:

   ```bash
   cd src/runtime/java
   mvn install -DskipTests
   ```

2. Build the Rust FFI library (optional, for full integration):
   ```bash
   cd src/runtime/core
   cargo build --no-default-features --features ffi --release
   ```

## Running

### 1. Start the Registry

```bash
meshctl start --registry-only
```

### 2. Start an LLM Provider

The analyst agent delegates LLM calls to a provider via mesh:

```bash
# Using Python LLM provider
meshctl start -d examples/llm-provider/claude_provider.py

# Or using Java LLM provider
cd examples/java/llm-provider-agent
mvn spring-boot:run
```

### 3. (Optional) Start Data Tools

For the agentic loop to work, start some data tools:

```bash
meshctl start -d examples/data-tools/weather_service.py
meshctl start -d examples/data-tools/stock_service.py
```

### 4. Run This Agent

```bash
cd examples/java/llm-mesh-agent

# With Maven
mvn spring-boot:run

# Or build and run JAR
mvn package
java -jar target/llm-mesh-agent-1.0.0-SNAPSHOT.jar
```

### 5. Test with meshctl

```bash
# List agents
meshctl list
# Output: analyst  healthy  http://localhost:9002

# List tools
meshctl list -t
# Output: analyze, chat

# Call analyze (structured output)
meshctl call analyze '{"ctx": {"query": "What is the weather in NYC?", "dataSource": "weather-api"}}'

# Simple chat
meshctl call chat '{"message": "Hello, how are you?"}'
```

## Configuration

Override settings via environment variables:

| Variable                | Description     | Default                 |
| ----------------------- | --------------- | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL    | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port | `9002`                  |
| `MCP_MESH_AGENT_NAME`   | Agent name      | `analyst`               |
| `MCP_MESH_NAMESPACE`    | Mesh namespace  | `default`               |

Example:

```bash
MCP_MESH_HTTP_PORT=9020 MCP_MESH_AGENT_NAME=analyst-2 mvn spring-boot:run
```

## Code Structure

```
src/main/java/com/example/analyst/
└── AnalystAgentApplication.java   # Main app with @MeshLlm tools

src/main/resources/
├── application.yml                # Spring Boot configuration
└── prompts/
    └── analyst.ftl               # Freemarker system prompt template

src/test/java/com/example/analyst/
└── AnalystAgentTest.java          # Unit tests with mocks
```

## Tools Provided

### `analyze`

AI-powered data analysis with agentic tool use.

**LLM Configuration:**

- Provider: Mesh delegation (`capability=llm`, prefer `+claude`, `+anthropic`)
- Max iterations: 5
- System prompt: Freemarker template
- Tool filter: `tags=["data", "tools"]`

**Parameters:**

- `ctx` (object, required): Analysis context
  - `query` (string): The analysis query
  - `dataSource` (string): Data source identifier
  - `parameters` (object): Additional parameters

**Response:**

```json
{
  "summary": "Weather is sunny with mild temperatures",
  "insights": ["Temperature is 72F", "No rain expected"],
  "confidence": 0.85,
  "source": "mesh:llm"
}
```

### `chat`

Simple chat using mesh LLM.

**LLM Configuration:**

- Provider: Mesh delegation (`capability=llm`)
- Max iterations: 1
- System prompt: "You are a helpful assistant."

**Parameters:**

- `message` (string, required): User message

**Response:**

```json
{
  "response": "Hello! How can I help you today?",
  "timestamp": "2026-01-29T12:00:00",
  "source": "mesh:llm"
}
```

## Key Concepts

### Mesh LLM Delegation

Instead of calling LLM APIs directly, this agent delegates to an LLM provider via mesh:

```java
@MeshLlm(
    providerSelector = @Selector(
        capability = "llm",
        tags = {"+claude", "+anthropic"}  // Prefer Claude providers
    ),
    maxIterations = 5,
    systemPrompt = "classpath:prompts/analyst.ftl",
    contextParam = "ctx"
)
public AnalysisResult analyze(AnalysisContext ctx, MeshLlmAgent llm) {
    return llm.generate(userPrompt, AnalysisResult.class);
}
```

### Freemarker Templates

System prompts support Freemarker templates with context injection:

```freemarker
## Query
${ctx.query!"No query provided"}

<#if tools?? && tools?has_content>
## Available Tools
<#list tools as tool>
- **${tool.name}**: ${tool.description}
</#list>
</#if>
```

### Structured Output

The LLM is instructed to return JSON matching the record structure:

```java
public record AnalysisResult(
    String summary,
    List<String> insights,
    double confidence,
    String source
) {}

// LLM returns JSON, SDK parses to record
return llm.generate(prompt, AnalysisResult.class);
```

### Agentic Loop

With `maxIterations > 1`, the LLM can call tools and reason:

1. LLM receives prompt + available tools
2. LLM decides to call a tool (e.g., `get_weather`)
3. Agent executes tool via mesh
4. Result returned to LLM
5. LLM continues reasoning or generates final response
6. Repeat up to `maxIterations` times
