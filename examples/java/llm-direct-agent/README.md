# LLM Direct Agent (Java)

An MCP Mesh agent demonstrating `@MeshLlm` with direct Spring AI calls.

## What This Example Shows

- `@MeshLlm(provider = "claude")` - Direct API calls via Spring AI
- No mesh delegation - API key required locally
- Different LLM configurations for different use cases
- Temperature tuning (low for accuracy, high for creativity)

## Direct vs Mesh LLM

```
llm-mesh-agent:    User -> Agent -> Mesh -> LLM Provider Agent -> Claude API
llm-direct-agent:  User -> Agent -> Spring AI -> Claude API (direct)
```

**When to Use Direct:**

- Single agent deployment
- Simpler setup (no LLM provider agent needed)
- API key managed locally
- Lower latency (no mesh hop)

**When to Use Mesh:**

- Multiple agents share LLM provider
- Centralized API key management
- Rate limiting at provider level
- LLM provider can be swapped without redeploying agents

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

### 2. Run the Agent

```bash
cd examples/java/llm-direct-agent

# With Maven
ANTHROPIC_API_KEY=your-key mvn spring-boot:run

# Or build and run JAR
mvn package
ANTHROPIC_API_KEY=your-key java -jar target/llm-direct-agent-1.0.0-SNAPSHOT.jar
```

### 3. Test with meshctl

```bash
# List agents
meshctl list
# Output: chatbot  healthy  http://localhost:9003

# List tools
meshctl list -t
# Output: chat, creative_write, explain_code

# Simple chat
meshctl call chat '{"message": "Hello, how are you?"}'

# Creative writing
meshctl call creative_write '{"prompt": "Write a haiku about Java programming"}'

# Code explanation
meshctl call explain_code '{"code": "public static void main(String[] args)", "language": "java"}'
```

## Configuration

Override settings via environment variables:

| Variable                | Description       | Default                 |
| ----------------------- | ----------------- | ----------------------- |
| `ANTHROPIC_API_KEY`     | Anthropic API key | (required)              |
| `MCP_MESH_REGISTRY_URL` | Registry URL      | `http://localhost:8000` |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port   | `9003`                  |
| `MCP_MESH_AGENT_NAME`   | Agent name        | `chatbot`               |

## Code Structure

```
src/main/java/com/example/chatbot/
└── ChatbotAgentApplication.java   # Main app with @MeshLlm tools

src/main/resources/
└── application.yml                # Spring Boot + Spring AI configuration

src/test/java/com/example/chatbot/
└── ChatbotAgentTest.java          # Unit tests with mocks
```

## Tools Provided

### `chat`

Interactive chat with Claude.

**LLM Configuration:**

- Provider: Direct Claude (Spring AI)
- Temperature: 0.7 (balanced)
- Max tokens: 1024

**Parameters:**

- `message` (string, required): User message

**Response:**

```json
{
  "input": "Hello, how are you?",
  "response": "I'm doing well, thanks for asking! How can I help you today?",
  "timestamp": "2026-01-29T12:00:00",
  "source": "direct:claude"
}
```

### `creative_write`

Creative writing with Claude.

**LLM Configuration:**

- Provider: Direct Claude
- Temperature: 0.9 (creative)
- Max tokens: 2048

**Parameters:**

- `prompt` (string, required): Creative writing prompt

### `explain_code`

Explain code with Claude.

**LLM Configuration:**

- Provider: Direct Claude
- Temperature: 0.3 (accurate)
- Max tokens: 2048

**Parameters:**

- `code` (string, required): Code snippet to explain
- `language` (string, required): Programming language

## Key Concepts

### Direct Provider

```java
@MeshLlm(
    provider = "claude",  // Direct API via Spring AI
    maxIterations = 1,
    systemPrompt = "You are a helpful assistant.",
    maxTokens = 1024,
    temperature = 0.7
)
public ChatResponse chat(String message, MeshLlmAgent llm) {
    return llm.generate(message);  // Calls Anthropic API directly
}
```

### Temperature Tuning

Different use cases benefit from different temperatures:

```java
// Accurate/factual (low temperature)
temperature = 0.3  // Code explanation, Q&A

// Balanced (default)
temperature = 0.7  // General chat

// Creative (high temperature)
temperature = 0.9  // Creative writing, brainstorming
```

### Spring AI Configuration

Configure the Claude model in `application.yml`:

```yaml
spring:
  ai:
    anthropic:
      api-key: ${ANTHROPIC_API_KEY}
      chat:
        options:
          model: claude-sonnet-4-5
          max-tokens: 4096
```
