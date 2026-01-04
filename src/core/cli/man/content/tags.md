# Tag Matching System

> Smart service selection using tags with +/- operators

## Overview

Tags are metadata labels attached to capabilities that enable intelligent service selection. MCP Mesh supports "smart matching" with operators that express preferences and exclusions.

Tags are part of the **Capability Selector** syntax used throughout MCP Mesh. See `meshctl man capabilities` for the complete selector reference.

## Tag Operators (Consumer Side)

Use these operators when **selecting** capabilities (dependencies, providers, filters):

| Prefix | Meaning   | Example                                 |
| ------ | --------- | --------------------------------------- |
| (none) | Required  | `"api"` - must have this tag            |
| `+`    | Preferred | `"+fast"` - bonus if present            |
| `-`    | Excluded  | `"-deprecated"` - hard failure if found |

**Note:** Operators are for consumers only. When declaring tags on your tool, use plain strings without +/- prefixes.

## Declaring Tags (Provider Side)

```python
@mesh.tool(
    capability="weather_data",
    tags=["weather", "current", "api", "free"],
)
def get_weather(city: str): ...
```

## Using Tags in Dependencies

### Simple Tag Filter

```python
@mesh.tool(
    dependencies=[
        {"capability": "weather_data", "tags": ["api"]},
    ],
)
def my_tool(weather: mesh.McpMeshAgent = None): ...
```

### Smart Matching with Operators

```python
@mesh.tool(
    dependencies=[
        {
            "capability": "weather_data",
            "tags": [
                "api",           # Required: must have "api" tag
                "+accurate",     # Preferred: bonus if "accurate"
                "+fast",         # Preferred: bonus if "fast"
                "-deprecated",   # Excluded: fail if "deprecated"
            ],
        },
    ],
)
def my_tool(weather: mesh.McpMeshAgent = None): ...
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

```python
# Prefer Claude > GPT > any other LLM
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+anthropic", "+gpt"]},
)
def my_llm_tool(): ...
```

| Provider | Its Tags | Matches | Score |
|----------|----------|---------|-------|
| Claude | `["llm", "claude", "anthropic"]` | +claude, +anthropic | **+2** |
| GPT | `["llm", "gpt", "openai"]` | +gpt | **+1** |
| Llama | `["llm", "llama"]` | (none) | **+0** |

Result: Claude (+2) > GPT (+1) > Llama (+0)

This works for any capability selection (dependencies, providers, tool filters).

## Tool Filtering in @mesh.llm

Filter which tools an LLM agent can access:

```python
@mesh.llm(
    filter=[
        {"tags": ["executor", "tools"]},      # Tools with these tags
        {"capability": "calculator"},          # Or this specific capability
    ],
    filter_mode="all",  # Include all matching
)
def smart_assistant(): ...
```

## See Also

- `meshctl man capabilities` - Capabilities system
- `meshctl man llm` - LLM integration
- `meshctl man dependency-injection` - How DI works
