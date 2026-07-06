<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/llm/index/">Python LLM Integration</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../java/llm/index/">Java LLM Integration</a></span>
</div>

# LLM Integration (TypeScript)

> Building LLM-powered agents with mesh.llm()

## Overview

MCP Mesh provides first-class support for LLM-powered agents through `mesh.llm()`. This enables agentic loops where LLMs can discover and use mesh tools automatically.

## What's Included

The `@mcpmesh/sdk` package includes LLM support out of the box via the Vercel AI SDK:

- **Claude** (Anthropic) - `@ai-sdk/anthropic`
- **GPT** (OpenAI) - `@ai-sdk/openai`

No additional packages needed. Just set your API keys:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

## mesh.llm() Function

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Smart Assistant", version: "1.0.0" });
const agent = mesh(server, { name: "smart-assistant", httpPort: 9003 });

agent.addTool({
  name: "assist",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] },
    maxIterations: 5,
    systemPrompt: "file://prompts/assistant.hbs",
    contextParam: "ctx",
    filter: [{ tags: ["tools"] }],
    filterMode: "all",
  }),
  capability: "smart_assistant",
  description: "LLM-powered assistant",
  parameters: z.object({
    ctx: z.object({
      query: z.string(),
    }),
  }),
  execute: async ({ ctx }, { llm }) => {
    return llm("Help the user with their request");
  },
});
```

## Parameters

| Parameter       | Type              | Description                                      |
| --------------- | ----------------- | ------------------------------------------------ |
| `provider`      | `LlmProviderSpec` | LLM provider selector (capability + tags)        |
| `maxIterations` | `number`          | Max agentic loop iterations (default: 10)        |
| `systemPrompt`  | `string`          | System prompt or file path (Handlebars template) |
| `contextParam`  | `string`          | Parameter name passed to template context        |
| `filter`        | `LlmFilterSpec[]` | Tool filter for discovery                        |
| `filterMode`    | `string`          | How to select tools: "all", "best_match", "\*"   |
| `responseModel` | `ZodType`         | Optional: Schema the LLM must emit (drives structured output) |
| `returns`       | `ZodType`         | Optional: Schema for what `execute` returns to callers |

When `responseModel` is set, it is the schema the LLM is required to emit and is validated against, and it drives the provider's structured-output schema; the injected `llm` callable is typed by it. `returns` independently types what `execute` returns to callers. When `responseModel` is omitted, the LLM schema falls back to `returns`. Separating the two lets a tool combine LLM-produced fields with deterministic, function-computed fields without forcing the LLM to emit the deterministic ones.

## Provider Selector

Select LLM providers using capability and tag matching:

```typescript
// Simple: just capability name
provider: "llm"

// With tags for specific provider
provider: { capability: "llm", tags: ["+claude"] }

// Exclude certain providers
provider: { capability: "llm", tags: ["-openai"] }
```

## System Prompts with Handlebars

System prompts support Handlebars templating:

```typescript
// Inline prompt
systemPrompt: "You are a helpful assistant. User context: {{ctx.user}}";

// File-based prompt
systemPrompt: "file://prompts/assistant.hbs";
```

Template file (`prompts/assistant.hbs`):

```handlebars
You are a helpful assistant. User:
{{ctx.user.name}}
Query:
{{ctx.query}}

Available tools will be provided. Use them to help the user.
```

## Structured Output

Use Zod schemas for type-safe structured responses:

```typescript
import { z } from "zod";

const AssistResponse = z.object({
  answer: z.string(),
  confidence: z.number().min(0).max(1),
  sources: z.array(z.string()).optional(),
});

agent.addTool({
  name: "analyze",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] },
    systemPrompt: "Analyze the query and provide a structured response.",
    returns: AssistResponse, // Enables structured output
  }),
  capability: "analyzer",
  description: "Analyzes queries with structured output",
  parameters: z.object({
    query: z.string(),
  }),
  execute: async ({ query }, { llm }) => {
    // Returns AssistResponse type
    const result = await llm(query);
    return JSON.stringify(result);
  },
});
```

### Separating LLM output from deterministic fields

Use `responseModel` for the schema the LLM must emit and `returns` for what
`execute` returns to callers. This keeps the LLM focused on the fields it
should produce, while `execute` adds deterministic, function-computed fields:

```typescript
const runDaily = mesh.llm({
  name: "run_daily",
  provider: { capability: "llm", tags: ["+openai"] },
  parameters: z.object({ email: z.string() }),
  responseModel: AnalystOutput,   // what the LLM must emit (focused)
  returns: RunDailyResult,        // what execute returns to callers (LLM fields + deterministic context)
  execute: async ({ email }, { llm }) => {
    const analyst = await llm("...");                 // typed/validated as AnalystOutput
    return { ...analyst, email, date: today(), totalValue }; // RunDailyResult
  },
});
```

## Tool Filtering

Control which mesh tools the LLM can access:

```typescript
// All tools with specific tags
filter: [{ tags: ["tools", "safe"] }];

// Specific capabilities
filter: [{ capability: "calculator" }, { capability: "weather" }];

// Mixed filtering
filter: [{ capability: "data", tags: ["+fast"] }, { tags: ["utility"] }];
```

### Filter Modes

| Mode         | Description                                |
| ------------ | ------------------------------------------ |
| `all`        | Include all tools matching any filter      |
| `best_match` | One tool per capability (best tag match)   |
| `*`          | All available tools in the mesh (wildcard) |

## Creating LLM Providers

Create zero-code LLM providers with `agent.addLlmProvider()`:

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";

const server = new FastMCP({ name: "Claude Provider", version: "1.0.0" });
const agent = mesh(server, { name: "claude-provider", httpPort: 9001 });

// Single provider (default name: "process_chat")
agent.addLlmProvider({
  model: "anthropic/claude-sonnet-4-5",
  capability: "llm",
  tags: ["llm", "claude", "provider"],
});

// Multiple providers in one agent (use custom names)
agent.addLlmProvider({
  name: "sonnet_chat", // Custom tool name
  model: "anthropic/claude-sonnet-4-5",
  capability: "llm",
  tags: ["llm", "claude", "sonnet"],
});

agent.addLlmProvider({
  name: "opus_chat", // Different tool name
  model: "anthropic/claude-opus-4",
  capability: "llm",
  tags: ["llm", "claude", "opus"],
});
```

### LLM Provider Parameters

| Parameter     | Type       | Default          | Description                                                |
| ------------- | ---------- | ---------------- | ---------------------------------------------------------- |
| `model`       | `string`   | (required)       | LiteLLM model format (e.g., "anthropic/claude-sonnet-4-5") |
| `name`        | `string`   | `"process_chat"` | Tool name for MCP registration                             |
| `capability`  | `string`   | `"llm"`          | Capability name for mesh discovery                         |
| `tags`        | `string[]` | `[]`             | Tags for provider selection                                |
| `version`     | `string`   | `"1.0.0"`        | Version for mesh registration                              |
| `maxTokens`   | `number`   | (model default)  | Maximum tokens to generate                                 |
| `temperature` | `number`   | (model default)  | Sampling temperature                                       |
| `topP`        | `number`   | (model default)  | Top-p sampling                                             |
| `description` | `string`   | (auto-generated) | Tool description                                           |

### Supported Models

Uses LiteLLM model format:

| Provider                | Model Format                   |
| ----------------------- | ------------------------------ |
| Anthropic               | `anthropic/claude-sonnet-4-5`  |
| OpenAI                  | `openai/gpt-4o`                |
| Google AI Studio        | `gemini/gemini-2.5-flash`      |
| Google Vertex AI (IAM)  | `vertex_ai/gemini-2.5-flash`   |
| Mistral                 | `mistral/mistral-large-latest` |
| Ollama                  | `ollama/llama3`                |

## Vertex AI (Gemini via IAM)

The TypeScript runtime supports Gemini via Google Cloud Vertex AI as an
alternative to AI Studio. Same model family, same `GeminiHandler`, same
HINT-mode prompt shaping for structured output with tools — only the model
prefix and auth env vars change.

### When to use Vertex AI vs AI Studio

| Use case                                              | Pick                                                  |
| ----------------------------------------------------- | ----------------------------------------------------- |
| Quickstart / dev / lowest setup                       | AI Studio (`gemini/*`, `GOOGLE_GENERATIVE_AI_API_KEY`) |
| Production with IAM auth, GCP audit logs, VPC-SC      | Vertex AI (`vertex_ai/*`, ADC)                        |
| Need Provisioned Throughput (no capacity 429s)        | Vertex AI (Provisioned Throughput is GCP-side)        |
| Multi-tenant org-controlled billing                   | Vertex AI                                             |

### Setup

`@ai-sdk/google-vertex` is bundled with `@mcpmesh/sdk` — no extra install
needed.

1. Configure GCP Application Default Credentials. Pick one:

   **User ADC** (dev):

   ```bash
   gcloud auth application-default login
   export GOOGLE_CLOUD_PROJECT=my-gcp-project
   export GOOGLE_CLOUD_LOCATION=us-central1
   ```

   **Service account** (CI / prod):

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
   export GOOGLE_CLOUD_PROJECT=my-gcp-project
   export GOOGLE_CLOUD_LOCATION=us-central1
   ```

   Both vars are required — there is no default location and the project is
   not auto-discovered from ADC. Common location values: `us-central1`,
   `global`.

2. Use the `vertex_ai/*` model prefix:

   ```typescript
   agent.addLlmProvider({
     model: "vertex_ai/gemini-2.5-flash",
     capability: "llm",
     tags: ["llm", "gemini", "vertex"],
   });
   ```

That's it. Same agent code as the AI Studio path; mesh's `GeminiHandler` is
selected automatically and applies HINT-mode prompt shaping when the call
involves tools (avoiding Gemini's response_format-with-tools deadlock).

### Switching backends

Migrate from AI Studio to Vertex AI by changing the model prefix and env vars:

```typescript
// before:
model: "gemini/gemini-2.5-flash";
// after:
model: "vertex_ai/gemini-2.5-flash";
```

```bash
# before:
export GOOGLE_GENERATIVE_AI_API_KEY=AIza...
# after:
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=my-gcp-project
export GOOGLE_CLOUD_LOCATION=us-central1
```

No other code changes required.

### Reference example

See `examples/typescript/vertex-ai-agent/` for a working minimal agent.

## Complete Example

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// 1. Create LLM Provider
const providerServer = new FastMCP({ name: "Claude", version: "1.0.0" });
const provider = mesh(providerServer, {
  name: "claude-provider",
  httpPort: 9001,
});

provider.addLlmProvider({
  name: "chat",
  model: "anthropic/claude-sonnet-4-5",
  capability: "llm",
  tags: ["llm", "claude"],
});

// 2. Create Tool Agent
const toolServer = new FastMCP({ name: "Calculator", version: "1.0.0" });
const calculator = mesh(toolServer, { name: "calculator", httpPort: 9002 });

calculator.addTool({
  name: "add",
  capability: "calculator_add",
  tags: ["tools", "math"],
  description: "Add two numbers",
  parameters: z.object({ a: z.number(), b: z.number() }),
  execute: async ({ a, b }) => String(a + b),
});

// 3. Create LLM Agent
const agentServer = new FastMCP({ name: "Smart Assistant", version: "1.0.0" });
const assistant = mesh(agentServer, {
  name: "smart-assistant",
  httpPort: 9003,
});

assistant.addTool({
  name: "assist",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude"] },
    systemPrompt: "You are a helpful assistant with access to a calculator.",
    filter: [{ tags: ["tools"] }],
    maxIterations: 5,
  }),
  capability: "assistant",
  description: "LLM-powered assistant",
  parameters: z.object({ message: z.string() }),
  execute: async ({ message }, { llm }) => llm(message),
});
```

## See Also

- `meshctl man decorators --typescript` - All mesh functions
- `meshctl man tags` - Tag matching for provider selection
- `meshctl man capabilities` - Capability discovery
