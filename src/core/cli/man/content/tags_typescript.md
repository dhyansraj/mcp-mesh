# Tag Matching System (TypeScript)

> Smart service selection using tags with +/- operators

## Overview

Tags are metadata labels attached to capabilities that enable intelligent service selection. MCP Mesh supports "smart matching" with operators that express preferences and exclusions.

Tags are part of the **Capability Selector** syntax used throughout MCP Mesh. See `meshctl man capabilities --typescript` for the complete selector reference.

## Tag Operators (Consumer Side)

Use these operators when **selecting** capabilities (dependencies, providers, filters):

| Prefix | Meaning   | Example                                 |
| ------ | --------- | --------------------------------------- |
| (none) | Required  | `"api"` - must have this tag            |
| `+`    | Preferred | `"+fast"` - bonus if present            |
| `-`    | Excluded  | `"-deprecated"` - hard failure if found |

**Note:** Operators are for consumers only. When declaring tags on your tool, use plain strings without +/- prefixes.

## Declaring Tags (Provider Side)

```typescript
import { z } from "zod";

agent.addTool({
  name: "get_weather",
  capability: "weather_data",
  tags: ["weather", "current", "api", "free"],  // Plain strings
  parameters: z.object({ city: z.string() }),
  execute: async ({ city }) => {
    return JSON.stringify({ city, temp: 72 });
  },
});
```

## Using Tags in Dependencies

### Simple Tag Filter

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: [
    { capability: "weather_data", tags: ["api"] },
  ],
  parameters: z.object({}),
  execute: async ({}, { weather_data }) => {
    if (weather_data) {
      return await weather_data({ city: "NYC" });
    }
    return "Weather service unavailable";
  },
});
```

### Smart Matching with Operators

```typescript
agent.addTool({
  name: "smart_weather",
  capability: "smart_weather",
  dependencies: [
    {
      capability: "weather_data",
      tags: [
        "api",           // Required: must have "api" tag
        "+accurate",     // Preferred: bonus if "accurate"
        "+fast",         // Preferred: bonus if "fast"
        "-deprecated",   // Excluded: fail if "deprecated"
      ],
    },
  ],
  parameters: z.object({}),
  execute: async ({}, { weather_data }) => {
    if (weather_data) {
      return await weather_data({ city: "NYC" });
    }
    return "No suitable weather service found";
  },
});
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

Filter: `["api", "+accurate", "+fast", "-deprecated"]`

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

```typescript
// Prefer Claude > GPT > any other LLM
agent.addTool({
  name: "smart_chat",
  ...mesh.llm({
    provider: { capability: "llm", tags: ["+claude", "+anthropic", "+gpt"] },
    systemPrompt: "You are helpful.",
  }),
  capability: "chat",
  parameters: z.object({ message: z.string() }),
  execute: async ({ message }, { llm }) => llm(message),
});
```

| Provider | Its Tags | Matches | Score |
|----------|----------|---------|-------|
| Claude | `["llm", "claude", "anthropic"]` | +claude, +anthropic | **+2** |
| GPT | `["llm", "gpt", "openai"]` | +gpt | **+1** |
| Llama | `["llm", "llama"]` | (none) | **+0** |

Result: Claude (+2) > GPT (+1) > Llama (+0)

This works for any capability selection (dependencies, providers, tool filters).

## Tool Filtering in mesh.llm()

Filter which tools an LLM agent can access:

```typescript
agent.addTool({
  name: "smart_assistant",
  ...mesh.llm({
    provider: { capability: "llm" },
    filter: [
      { tags: ["executor", "tools"] },    // Tools with these tags
      { capability: "calculator" },        // Or this specific capability
    ],
    filterMode: "all",  // Include all matching
    systemPrompt: "You are a helpful assistant.",
  }),
  capability: "assistant",
  parameters: z.object({ query: z.string() }),
  execute: async ({ query }, { llm }) => llm(query),
});
```

## Filter Modes

| Mode         | Description                              |
| ------------ | ---------------------------------------- |
| `all`        | Include all tools matching any filter    |
| `best_match` | One tool per capability (best tag match) |
| `*`          | All available tools (wildcard)           |

## Complete Example

```typescript
import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Weather Consumer", version: "1.0.0" });
const agent = mesh(server, { name: "weather-consumer", httpPort: 9000 });

// Tool that prefers fast, accurate weather with fallback
agent.addTool({
  name: "get_forecast",
  capability: "forecast",
  dependencies: [
    {
      capability: "weather_data",
      tags: [
        "api",           // Must have API access
        "+accurate",     // Prefer accurate
        "+fast",         // Prefer fast
        "+premium",      // Prefer premium
        "-deprecated",   // Never use deprecated
        "-beta",         // Avoid beta services
      ],
    },
  ],
  parameters: z.object({
    city: z.string(),
    days: z.number().default(5),
  }),
  execute: async ({ city, days }, { weather_data }) => {
    if (!weather_data) {
      return JSON.stringify({
        error: "No weather service available",
        suggestion: "Check mesh status with 'meshctl list'",
      });
    }

    const forecast = await weather_data({ city, forecast_days: days });
    return forecast;
  },
});
```

## See Also

- `meshctl man capabilities --typescript` - Capabilities system
- `meshctl man llm --typescript` - LLM integration
- `meshctl man dependency-injection --typescript` - How DI works
