<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../java/llm/index/">Java LLM Integration</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/llm/index/">TypeScript LLM Integration</a></span>
</div>

# LLM Integration

> Building LLM-powered agents with @mesh.llm decorator

**Note:** This page shows Python examples. See `meshctl man llm --typescript` for TypeScript or `meshctl man llm --java` for Java/Spring Boot examples.

## Overview

MCP Mesh provides first-class support for LLM-powered agents through the `@mesh.llm` decorator (Python), `@MeshLlm` annotation (Java), or `mesh.llm()` wrapper (TypeScript). This enables agentic loops where LLMs can discover and use mesh tools automatically.

## What's Included

The `mcp-mesh` package includes LLM support out of the box via LiteLLM:

- **Claude** (Anthropic)
- **GPT** (OpenAI)
- **And 100+ other providers** via LiteLLM

No additional packages needed. Just set your API keys:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

## @mesh.llm Decorator

```python
@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=5,
    system_prompt="file://prompts/assistant.jinja2",
    context_param="ctx",
    filter=[{"tags": ["tools"]}],
    filter_mode="all",
)
@mesh.tool(
    capability="smart_assistant",
    description="LLM-powered assistant",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Help the user with their request")
```

## Parameters

| Parameter        | Type | Description                                       |
| ---------------- | ---- | ------------------------------------------------- |
| `provider`       | dict | LLM provider selector (capability + tags)         |
| `max_iterations` | int  | Max agentic loop iterations (default: 1)          |
| `system_prompt`  | str  | Inline prompt or `file://path` to Jinja2 template |
| `context_param`  | str  | Parameter name receiving context object           |
| `filter`         | list | Tool filter criteria                              |
| `filter_mode`    | str  | `"all"`, `"best_match"`, or `"*"`                 |
| `<llm_params>`   | any  | LiteLLM params (max_tokens, temperature, etc.)    |

**Note**: `provider` and `filter` use the capability selector syntax (`capability`, `tags`, `version`). See `meshctl man capabilities` for details.

**Note**: Response format is determined by the function's return type annotation, not a parameter. See [Response Formats](#response-formats).

## LLM Model Parameters

Pass any LiteLLM parameter in the decorator as defaults:

```python
@mesh.llm(
    provider={"capability": "llm"},
    max_tokens=16000,
    temperature=0.7,
    top_p=0.9,
)
def assist(ctx, llm = None):
    # Uses decorator defaults
    return llm("Help the user")

    # Override at call time
    return llm("Help", max_tokens=8000)
```

Call-time parameters take precedence over decorator defaults.

## Response Metadata

LLM results include `_mesh_meta` for cost tracking and debugging:

```python
result = await llm("Analyze this")
print(result._mesh_meta.model)          # "openai/gpt-4o"
print(result._mesh_meta.input_tokens)   # 100
print(result._mesh_meta.output_tokens)  # 50
print(result._mesh_meta.latency_ms)     # 125.5
```

## LLM Provider Selection

Select LLM provider using capability and tags:

```python
# Prefer Claude
provider={"capability": "llm", "tags": ["+claude"]}

# Require OpenAI
provider={"capability": "llm", "tags": ["openai"]}

# Any LLM provider
provider={"capability": "llm"}
```

### Model Override

Override provider's default model at the consumer:

```python
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    model="anthropic/claude-haiku",  # Override provider default
)
def fast_assist(ctx, llm = None):
    return llm("Quick response needed")
```

Vendor mismatch (e.g., requesting OpenAI model from Claude provider) logs a warning and falls back to provider default.

## Creating LLM Providers

Use `@mesh.llm_provider` for zero-code LLM providers:

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["llm", "claude", "provider"],
    version="1.0.0",
)
def claude_provider():
    pass  # No implementation needed

@mesh.agent(name="claude-provider", http_port=9110)
class ClaudeProviderAgent:
    pass
```

### Supported Models (LiteLLM)

```
anthropic/claude-sonnet-4-5
anthropic/claude-opus-4
openai/gpt-4o
openai/gpt-4-turbo
openai/gpt-3.5-turbo
gemini/gemini-2.0-flash          # Google AI Studio (API key)
vertex_ai/gemini-2.0-flash       # Google Vertex AI (IAM)
```

## Vertex AI (Gemini via IAM)

mcp-mesh's Python runtime supports Gemini via Google Cloud Vertex AI as an
alternative to AI Studio. Same handler, same HINT-mode prompt shaping for
structured output with tools — only the model prefix and auth env vars change.

The TypeScript and Java runtimes have equivalent support — see
[TypeScript LLM Integration](../../typescript/llm/index/) and
[Java LLM Integration](../../java/llm/index/) for the runtime-specific
auth env vars (each follows its own ecosystem's naming convention).

### When to use Vertex AI vs AI Studio

| Use case                                              | Pick                                            |
| ----------------------------------------------------- | ----------------------------------------------- |
| Quickstart / dev / lowest setup                       | AI Studio (`gemini/*`, `GOOGLE_API_KEY`)        |
| Production with IAM auth, GCP audit logs, VPC-SC      | Vertex AI (`vertex_ai/*`, ADC)                  |
| Need Provisioned Throughput (no capacity 429s)        | Vertex AI (Provisioned Throughput is GCP-side)  |
| Multi-tenant org-controlled billing                   | Vertex AI                                       |

### Setup

1. Install the `vertex` extra:

   ```bash
   pip install 'mcp-mesh[vertex]'
   ```

   This adds `google-auth` (required by LiteLLM for ADC).

2. Configure auth + project + location (pick one path):

   **User ADC** (dev):

   ```bash
   gcloud auth application-default login
   export VERTEXAI_PROJECT=my-gcp-project
   export VERTEXAI_LOCATION=us-central1
   ```

   **Service account** (CI / prod):

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
   export VERTEXAI_LOCATION=us-central1
   ```

   **Workload Identity** (GKE):

   ```bash
   export VERTEXAI_LOCATION=us-central1
   ```

3. Use the `vertex_ai/*` prefix in your decorator:

   ```python
   @mesh.llm_provider(
       capability="llm",
       tags=["gemini", "vertex"],
       model="vertex_ai/gemini-2.0-flash",
   )
   def my_provider(): pass
   ```

That's it. Same agent code as the AI Studio path; mesh's `GeminiHandler` is
selected automatically and applies HINT-mode prompt shaping when the call
involves tools.

### Switching backends

To migrate an existing agent from AI Studio to Vertex AI:

```python
# Change one line in the decorator:
model="gemini/gemini-2.0-flash"      # was: "gemini/gemini-2.0-flash"
                                     # now: "vertex_ai/gemini-2.0-flash"
```

```bash
# Switch the env vars:
unset GOOGLE_API_KEY
export VERTEXAI_PROJECT=my-project
export VERTEXAI_LOCATION=us-central1
gcloud auth application-default login
```

No other changes required.

### Reference example

See `examples/python/vertex-ai-agent/` for a working minimal agent.

## Tool Filtering

Control which mesh tools the LLM can access using `filter` and `filter_mode`:

```python
filter=[{"tags": ["tools"]}],      # By tags
filter=[{"capability": "calc"}],   # By capability
filter_mode="*",                   # All tools (wildcard)
# Omit filter for no tools (LLM only)
```

For tag operators (+/-), matching algorithm, and advanced patterns, see `meshctl man tags`.

## System Prompts

### Inline Prompt

```python
system_prompt="You are a helpful assistant. Analyze the input and respond."
```

### Jinja2 Template File

```python
system_prompt="file://prompts/assistant.jinja2"
```

Template example:

```jinja2
You are {{ agent_name }}, an AI assistant.

## Context
{{ input_text }}

## Instructions
Analyze the input and provide a helpful response.
Available tools: {{ tools | join(", ") }}
```

**Note**: Context fields are accessed directly (`{{ input_text }}`), not via prefix.

## Context Objects

Define typed context with Pydantic:

```python
from pydantic import BaseModel, Field

class AssistContext(BaseModel):
    input_text: str = Field(..., description="User's request")
    user_id: str = Field(default="anonymous")
    preferences: dict = Field(default_factory=dict)

@mesh.llm(context_param="ctx", ...)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    return llm(f"Help with: {ctx.input_text}")
```

## Response Formats

Response format is determined by the **return type annotation** - not a decorator parameter.

| Return Type        | Output          | Description                   |
| ------------------ | --------------- | ----------------------------- |
| `-> str`           | Plain text      | LLM returns unstructured text |
| `-> PydanticModel` | Structured JSON | LLM returns validated object  |

### Text Response

```python
@mesh.llm(provider={"capability": "llm"}, ...)
@mesh.tool(capability="summarize")
def summarize(ctx: SummaryContext, llm: mesh.MeshLlmAgent = None) -> str:
    return llm("Summarize the input")  # Returns plain text
```

### Structured JSON Response

```python
class AssistResponse(BaseModel):
    answer: str
    confidence: float
    sources: list[str]

@mesh.llm(provider={"capability": "llm"}, ...)
@mesh.tool(capability="smart_assistant")
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Analyze and respond")  # Returns validated Pydantic object
```

## Agentic Loops

Set `max_iterations` for multi-step reasoning:

```python
@mesh.llm(
    max_iterations=10,  # Allow up to 10 tool calls
    filter=[{"tags": ["tools"]}],
)
def complex_task(ctx: TaskContext, llm: mesh.MeshLlmAgent = None):
    return llm("Complete this multi-step task")
```

The LLM will:

1. Analyze the request
2. Call discovered tools as needed
3. Use tool results for further reasoning
4. Return final response

## Runtime Context Injection

Pass additional context at call time to merge with or override auto-populated context:

```python
@mesh.llm(
    system_prompt="file://prompts/assistant.jinja2",
    context_param="ctx",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    # Default: uses ctx from context_param
    return llm("Help the user")

    # Add extra context (runtime wins on conflicts)
    return llm("Help", context={"extra_info": "value"})

    # Auto context wins on conflicts
    return llm("Help", context={"extra": "value"}, context_mode="prepend")

    # Replace context entirely
    return llm("Help", context={"only": "this"}, context_mode="replace")
```

### Context Modes

| Mode      | Behavior                                    |
| --------- | ------------------------------------------- |
| `append`  | auto_context \| runtime_context (default)   |
| `prepend` | runtime_context \| auto_context (auto wins) |
| `replace` | runtime_context only (ignores auto)         |

### Use Cases

**Multi-turn conversations** with state:

```python
async def chat(ctx: ChatContext, llm: mesh.MeshLlmAgent = None):
    # First turn
    response1 = await llm("Hello", context={"turn": 1})

    # Second turn with accumulated context
    response2 = await llm("Continue", context={"turn": 2, "prev": response1})

    return response2
```

**Conditional context**:

```python
async def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None):
    extra = {"premium": True} if ctx.user.is_premium else {}
    return await llm("Help", context=extra)
```

**Clear context** when not needed:

```python
# Explicitly clear all context
return await llm("Standalone query", context={}, context_mode="replace")
```

## Scaffolding LLM Agents

```bash
# Generate LLM agent
meshctl scaffold --name my-agent --agent-type llm-agent --llm-selector claude

# Generate LLM provider
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5
```

## See Also

- `meshctl man decorators` - All decorator options
- `meshctl man tags` - Tag matching for providers
- `meshctl man testing` - Testing LLM agents
