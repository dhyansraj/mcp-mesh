# Spring AI 1.0.0 Capability Findings for MCP Mesh Integration

## Executive Summary

This document captures findings from testing Spring AI 1.0.0 capabilities relevant to MCP Mesh's delegation mode, where an LLM provider agent returns tool calls without executing them, and a consumer agent handles execution.

**Key Discovery**: When `internalToolExecutionEnabled(false)` is set, Spring AI returns **multiple Generations** in the response - one for text content and one for tool calls. You must iterate through `getResults()` (plural) to find tool calls, not use `getResult()` (singular).

## Test Environment

- Spring Boot: 3.4.5
- Spring AI: 1.0.0 (stable)
- LLM Provider: Anthropic Claude (claude-sonnet-4-5)
- Java: 17

## Test Results Summary

| Test | Description                       | Result      |
| ---- | --------------------------------- | ----------- |
| 1    | Simple Chat (Baseline)            | SUCCESS     |
| 2    | Chat with Message History         | SUCCESS     |
| 3    | Tool Calling - Execution DISABLED | FAILED\*    |
| 4    | Tool Calling - Execution ENABLED  | SUCCESS     |
| 5    | Hint-Based Structured Output      | SUCCESS     |
| 6    | Direct Prompt API with Tools      | SUCCESS\*\* |

\* Test 3 failed because it used `getResult()` instead of iterating `getResults()`
\*\* Test 6 revealed the correct pattern for extracting tool calls

---

## Detailed Findings

### 1. Tool Calling with Execution Disabled (Critical for Mesh Delegation)

#### The Problem

When using `internalToolExecutionEnabled(false)`, calling `response.getResult().getOutput().hasToolCalls()` returns `false`, even though the LLM clearly wants to use tools (evidenced by `finishReason='tool_use'`).

#### The Solution

Spring AI splits the response into **multiple Generations**:

- **Generation[0]**: Contains text preamble (e.g., "I'll help you get the weather...")
  - `hasToolCalls() = false`
- **Generation[1]**: Contains the actual tool calls
  - `hasToolCalls() = true`
  - `getToolCalls()` returns the list of tool calls with `id`, `name`, and `arguments`

#### Correct Pattern for Extracting Tool Calls

```java
ToolCallingChatOptions options = ToolCallingChatOptions.builder()
    .toolCallbacks(toolCallback)
    .internalToolExecutionEnabled(false)  // Don't auto-execute
    .build();

Prompt prompt = new Prompt(messages, options);
ChatResponse response = chatModel.call(prompt);

// WRONG: This may not have tool calls
// response.getResult().getOutput().hasToolCalls()

// CORRECT: Iterate through all results
for (Generation gen : response.getResults()) {
    if (gen.getOutput().hasToolCalls()) {
        for (AssistantMessage.ToolCall tc : gen.getOutput().getToolCalls()) {
            String toolId = tc.id();      // e.g., "toolu_01XKfYGqjmwJ89ABZ2M7FdCZ"
            String toolName = tc.name();  // e.g., "getCityInfo"
            String toolArgs = tc.arguments();  // JSON string of arguments

            // Dispatch to remote agent via mesh...
        }
    }
}
```

#### Extracting Tool Calls Utility Method

```java
public List<AssistantMessage.ToolCall> extractToolCalls(ChatResponse response) {
    List<AssistantMessage.ToolCall> toolCalls = new ArrayList<>();
    for (Generation gen : response.getResults()) {
        if (gen.getOutput().hasToolCalls()) {
            toolCalls.addAll(gen.getOutput().getToolCalls());
        }
    }
    return toolCalls;
}
```

### 2. Chat with Message History

Message history works correctly using the `Prompt` API with a list of `Message` objects:

```java
List<Message> messages = new ArrayList<>();
messages.add(new SystemMessage("You are a helpful assistant."));
messages.add(new UserMessage("My name is Alice."));
messages.add(new AssistantMessage("Nice to meet you, Alice!"));
messages.add(new UserMessage("What is my name?"));

Prompt prompt = new Prompt(messages);
ChatResponse response = chatModel.call(prompt);
// Response correctly remembers "Alice"
```

**Important Types:**

- `SystemMessage` - System prompt
- `UserMessage` - User messages
- `AssistantMessage` - Previous assistant responses

### 3. Hint-Based Structured Output

For mesh delegation where you need structured responses without using Anthropic's native response_format, hint-based prompting works reliably:

```java
String systemPrompt = """
    You are a helpful assistant.

    RESPONSE FORMAT:
    You MUST respond with valid JSON matching this schema:
    {
      "summary": "string (required) - A brief summary",
      "confidence": "number (required) - A value from 0.0 to 1.0",
      "tags": "array of strings (required)"
    }

    Example:
    {"summary": "Example summary", "confidence": 0.8, "tags": ["tag1", "tag2"]}

    IMPORTANT: Respond ONLY with valid JSON. No markdown code fences, no preamble.
    """;
```

**Result**: Claude returns valid JSON that can be parsed directly with Jackson.

### 4. Tool Definition with FunctionToolCallback

```java
Function<Map<String, Object>, String> weatherFunc = args -> {
    String city = (String) args.getOrDefault("city", "unknown");
    return "{\"temperature\": 72, \"conditions\": \"sunny\"}";
};

@SuppressWarnings("unchecked")
ToolCallback weatherTool = FunctionToolCallback
    .builder("getWeather", weatherFunc)
    .description("Get the current weather for a city")
    .inputType((Class<Map<String, Object>>) (Class<?>) Map.class)
    .build();
```

**Note**: For mesh delegation, the function body is never actually executed locally (it's just a placeholder). The mesh runtime intercepts tool calls and routes them to remote agents.

---

## Implications for MCP Mesh Java SDK

### MeshLlmAgentProxy Updates Required

The `MeshLlmAgentProxy` class needs to be updated to:

1. **Extract tool calls from all Generations**, not just the first one:

```java
private List<AssistantMessage.ToolCall> extractToolCalls(ChatResponse response) {
    List<AssistantMessage.ToolCall> toolCalls = new ArrayList<>();
    for (Generation gen : response.getResults()) {
        if (gen.getOutput().hasToolCalls()) {
            toolCalls.addAll(gen.getOutput().getToolCalls());
        }
    }
    return toolCalls;
}
```

2. **Build tool result messages correctly**:

```java
// After executing tool on remote agent
ToolResponseMessage toolResponse = new ToolResponseMessage(
    List.of(new ToolResponseMessage.ToolResponse(
        toolCall.id(),
        toolCall.name(),
        resultJson
    )),
    Map.of()
);

// Add to message history for next LLM call
messages.add(originalAssistantMessage);  // Include original with tool_use
messages.add(toolResponse);
```

### Configuration Example

```properties
# Disable web server for command-line/agent applications
spring.main.web-application-type=none

# Anthropic configuration
spring.ai.anthropic.api-key=${ANTHROPIC_API_KEY}
spring.ai.anthropic.chat.options.model=claude-sonnet-4-5
spring.ai.anthropic.chat.options.max-tokens=4096

# Debug logging
logging.level.org.springframework.ai=DEBUG
```

---

## API Reference

### Key Classes

| Class                       | Purpose                                 |
| --------------------------- | --------------------------------------- |
| `ChatModel`                 | Interface for chat completions          |
| `AnthropicChatModel`        | Anthropic-specific implementation       |
| `ChatClient`                | Fluent API for simple chat interactions |
| `Prompt`                    | Container for messages and options      |
| `ChatResponse`              | Response container                      |
| `Generation`                | Single result within response           |
| `AssistantMessage`          | Output message from LLM                 |
| `AssistantMessage.ToolCall` | Tool call request (id, name, arguments) |
| `ToolCallingChatOptions`    | Options for tool configuration          |
| `FunctionToolCallback`      | Tool definition wrapper                 |
| `ToolResponseMessage`       | Tool execution result message           |

### Key Methods

```java
// Disable tool auto-execution
ToolCallingChatOptions.builder()
    .toolCallbacks(tools)
    .internalToolExecutionEnabled(false)
    .build();

// Get all results (not just first)
response.getResults()  // List<Generation>

// Check for tool calls
generation.getOutput().hasToolCalls()  // boolean

// Get tool calls
generation.getOutput().getToolCalls()  // List<ToolCall>

// Tool call properties
toolCall.id()        // String
toolCall.name()      // String
toolCall.arguments() // String (JSON)
```

---

## Version Compatibility Notes

| Spring Boot | Spring AI | Status                               |
| ----------- | --------- | ------------------------------------ |
| 3.5.x       | 2.0.0-M2  | INCOMPATIBLE (missing RetryTemplate) |
| 3.4.x       | 1.0.0     | COMPATIBLE                           |
| 3.4.x       | 1.0.0-M6  | COMPATIBLE                           |

Spring AI 2.0.0-M2 requires Spring Framework 6.3+ (RetryTemplate), which is only available in Spring Boot 3.5+. For stable builds, use Spring AI 1.0.0 with Spring Boot 3.4.x.

---

---

## Bug Fix Applied: MeshLlmProviderProcessor

Based on these findings, a critical bug was fixed in:
`src/runtime/java/mcp-mesh-spring-ai/src/main/java/io/mcpmesh/ai/MeshLlmProviderProcessor.java`

### The Bug

```java
// OLD (BROKEN): Only looked at first Generation
ChatResponse response = model.call(prompt);
Generation result = response.getResult();  // <- Problem: Only first generation
List<ToolCall> toolCalls = extractToolCalls(result);  // <- Missed tool calls!
```

### The Fix

```java
// NEW (FIXED): Iterate through ALL Generations
ChatResponse response = model.call(prompt);

String content = null;
List<ToolCall> toolCalls = new ArrayList<>();

for (Generation gen : response.getResults()) {
    AssistantMessage output = gen.getOutput();
    if (output == null) continue;

    // Capture text content from first generation that has it
    if (content == null && output.getText() != null && !output.getText().isEmpty()) {
        content = output.getText();
    }

    // Extract tool calls from any generation that has them
    if (output.hasToolCalls()) {
        for (ToolCall tc : output.getToolCalls()) {
            toolCalls.add(...);
        }
    }
}
```

---

## Conclusion

Spring AI 1.0.0 fully supports the mesh delegation pattern where:

1. Tool definitions are provided to the LLM
2. Tool execution is disabled (`internalToolExecutionEnabled(false)`)
3. Tool calls are extracted from the response
4. Tools are executed remotely via mesh
5. Results are fed back to continue the conversation

The key insight is that tool calls appear in a **separate Generation** within the response, requiring iteration through `getResults()` rather than using `getResult()`.

## Architecture Comparison: Java vs Python

Both SDKs now follow the same **Consumer-Side Loop** pattern:

```
Python:                              Java:
MeshLlmAgent (consumer)              MeshLlmAgentProxy (consumer)
       |                                    |
       |-- request(messages,tools) -------> |-- request(messages,tools)
       |                                    |
       v                                    v
LLM Provider (via mesh)              MeshLlmProviderProcessor
       |                                    |
       |-- calls LiteLLM                   |-- calls Spring AI
       |-- returns {content, tool_calls}   |-- returns {content, tool_calls}
       |                                    |
       v                                    v
Consumer receives tool_calls         Consumer receives tool_calls
       |                                    |
       |-- executes via mesh proxies       |-- executes via mesh proxies
       |-- adds results to messages        |-- adds results to messages
       |-- loops back to provider          |-- loops back to provider
       |                                    |
       v                                    v
Final response                       Final response
```

**Key Difference**: The agentic loop runs on the **consumer**, not the provider. The provider is stateless and just returns tool_calls for the consumer to execute.
