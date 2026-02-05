# LLM Integration with @mesh.llm

> Inject LLM agents as dependencies with automatic tool discovery and type-safe prompt templates

## What is @mesh.llm?

**New in v0.7**: MCP Mesh treats LLMs as first-class agents in the mesh. With `@mesh.llm()`, you can:

- 🤖 **Inject LLM agents** like any other dependency
- 🔍 **Auto-discover tools** based on capability filters
- 📝 **Type-safe prompt templates** using Jinja2 and Pydantic
- 🔗 **Dual injection** - combine LLM agents with MCP agents in one function
- 🎯 **Enhanced schemas** - Field descriptions help LLMs construct contexts correctly

This transforms LLMs from external services into orchestratable mesh capabilities.

## Quick Example

```python
import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("Analysis Service")

# 1. Simple LLM injection
@app.tool()
@mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
@mesh.tool(capability="simple_chat")
async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
    """LLM agent auto-injected, no configuration needed."""
    return await llm(message)

# 2. LLM with tool discovery filter
@app.tool()
@mesh.llm(
    system_prompt="You are a helpful system analyst.",
    filter={"tags": ["system"]},  # Auto-discover system tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="system_analysis")
async def analyze(query: str, llm: mesh.MeshLlmAgent = None) -> dict:
    """LLM automatically has access to all system-tagged tools."""
    return await llm(query)
```

## Core Concepts

### 1. LLM Dependency Injection

LLMs are injected as `MeshLlmAgent` parameters, just like MCP agents:

```python
@app.tool()
@mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")
@mesh.tool(capability="assistant")
async def help_user(
    question: str,
    llm: mesh.MeshLlmAgent = None  # ← Injected LLM agent
) -> str:
    if llm is None:
        return "LLM service unavailable"

    result = await llm(question)
    return result
```

### 2. Automatic Tool Discovery

Use `filter` to automatically discover and inject tools into the LLM's context:

```python
@app.tool()
@mesh.llm(
    filter={
        "capability": "weather_service",  # Specific capability
        "tags": ["weather", "forecast"]    # Or by tags
    },
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="weather_chat")
async def weather_assistant(query: str, llm: mesh.MeshLlmAgent = None):
    """LLM automatically gets weather tools without manual configuration."""
    return await llm(query)
```

The LLM will have access to all tools matching the filter - no manual tool specification needed!

### 3. Type-Safe Prompt Templates

Use Jinja2 templates with Pydantic models for validated, reusable prompts:

```python
from mesh import MeshContextModel

# Define type-safe context
class AnalysisContext(MeshContextModel):
    """Context for analysis prompts."""
    domain: str = Field(..., description="Analysis domain: infrastructure, security, or performance")
    user_level: str = Field(default="beginner", description="User expertise: beginner, intermediate, expert")
    focus_areas: list[str] = Field(default_factory=list, description="Specific areas to analyze")

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyst.jinja2",  # Load from file
    context_param="ctx",  # Which parameter contains context
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="analysis")
async def analyze_system(
    query: str,
    ctx: AnalysisContext,  # Type-safe context
    llm: mesh.MeshLlmAgent = None
) -> dict:
    # Template auto-rendered with ctx before LLM call
    return await llm(query)
```

**Template file** (`prompts/analyst.jinja2`):

```jinja2
You are a {{ domain }} analysis expert.
User expertise level: {{ user_level }}

{% if focus_areas %}
Focus your analysis on: {{ focus_areas | join(", ") }}
{% endif %}

Provide detailed analysis appropriate for {{ user_level }}-level users.
```

## @mesh.llm Decorator Reference

### Parameters

| Parameter        | Type   | Default    | Description                                        |
| ---------------- | ------ | ---------- | -------------------------------------------------- |
| `system_prompt`  | `str`  | `None`     | Literal prompt or `file://path/to/template.jinja2` |
| `filter`         | `dict` | `None`     | Tool discovery filter (capability, tags, version)  |
| `provider`       | `str`  | `"claude"` | LLM provider (claude, openai, etc.)                |
| `model`          | `str`  | Required   | Model identifier                                   |
| `context_param`  | `str`  | `None`     | Parameter name containing template context         |
| `max_iterations` | `int`  | `5`        | Max agentic loop iterations                        |

### Basic Usage Patterns

#### Pattern 1: Simple LLM Chat

```python
@app.tool()
@mesh.llm(
    system_prompt="You are a helpful assistant.",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="chat")
async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
    return await llm(message)
```

#### Pattern 2: LLM with Tool Access

```python
@app.tool()
@mesh.llm(
    system_prompt="You are a system administrator with access to monitoring tools.",
    filter={"tags": ["system", "monitoring"]},  # Auto-discover tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="system_admin")
async def admin_assistant(task: str, llm: mesh.MeshLlmAgent = None):
    return await llm(task)
```

#### Pattern 3: Template-Based Prompts

```python
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    context_param="ctx",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="personalized_chat")
async def chat(
    message: str,
    ctx: dict,  # Can be dict or MeshContextModel
    llm: mesh.MeshLlmAgent = None
):
    return await llm(message)
```

## Advanced: Dual Injection (LLM + MCP Agent)

**New in v0.7**: Inject both LLM agents AND MCP agents into the same function:

```python
from pydantic import BaseModel

class EnrichedResult(BaseModel):
    """LLM result enriched with MCP agent data."""
    analysis: str
    recommendations: list[str]
    timestamp: str
    system_info: str

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/dual_injection.jinja2",
    filter={"tags": ["system"]},  # LLM gets system tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(
    capability="enriched_analysis",
    dependencies=[{
        "capability": "date_service",
        "tags": ["system", "time"]
    }]  # Direct MCP agent dependency
)
async def analyze_with_enrichment(
    query: str,
    llm: mesh.MeshLlmAgent = None,        # ← Injected LLM
    date_service: mesh.McpMeshTool = None  # ← Injected MCP agent
) -> EnrichedResult:
    """Both LLM and MCP agents injected!"""

    # Step 1: Get LLM analysis (with system tools)
    llm_result = await llm(query)

    # Step 2: Call MCP agent directly for enrichment
    timestamp = await date_service() if date_service else "N/A"

    # Step 3: Combine results
    return EnrichedResult(
        analysis=llm_result.analysis,
        recommendations=llm_result.recommendations,
        timestamp=timestamp,
        system_info="Analysis enriched with real-time data"
    )
```

This pattern lets you:

- Use LLM for intelligent analysis (with filtered tool access)
- Call specific MCP agents directly for data enrichment
- Orchestrate both in a single, clean function

## MeshContextModel for Type Safety

`MeshContextModel` provides Pydantic-based validation for prompt contexts:

```python
from mesh import MeshContextModel
from pydantic import Field

class ChatContext(MeshContextModel):
    """Type-safe context for chat prompts."""
    user_name: str = Field(..., description="User's display name")
    domain: str = Field(..., description="Conversation domain")
    expertise_level: str = Field(
        default="beginner",
        description="User expertise: beginner, intermediate, expert"
    )

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    context_param="ctx",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="smart_chat")
async def chat(
    message: str,
    ctx: ChatContext,  # Validated at runtime
    llm: mesh.MeshLlmAgent = None
):
    # ctx is guaranteed to have user_name, domain, expertise_level
    return await llm(message)

# Usage
chat(
    "What's the weather?",
    ctx=ChatContext(
        user_name="Alice",
        domain="meteorology",
        expertise_level="expert"
    )
)
```

**Benefits:**

- ✅ Runtime validation of context fields
- ✅ IDE autocomplete for context attributes
- ✅ Self-documenting prompts
- ✅ Field descriptions exported to tool schemas

## Enhanced Schemas for LLM Chains

When LLMs call other LLMs, Field descriptions are automatically included in tool schemas:

```python
# Specialist LLM with MeshContextModel
class AnalysisContext(MeshContextModel):
    domain: str = Field(
        ...,
        description="Analysis domain: infrastructure, security, or performance"
    )
    user_level: str = Field(
        default="beginner",
        description="User expertise level: beginner, intermediate, or expert"
    )

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyst.jinja2",
    context_param="ctx",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="specialist_analysis")
async def analyze(request: str, ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None):
    return await llm(request)

# Orchestrator LLM that calls specialist
@app.tool()
@mesh.llm(
    filter={"capability": "specialist_analysis"},  # Discovers specialist
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="orchestrator")
async def orchestrate(task: str, llm: mesh.MeshLlmAgent = None):
    # LLM sees enhanced schema with Field descriptions
    # Knows domain is "infrastructure|security|performance"
    # Knows user_level is "beginner|intermediate|expert"
    return await llm(task)
```

The orchestrator LLM receives:

```json
{
  "name": "analyze",
  "inputSchema": {
    "properties": {
      "ctx": {
        "properties": {
          "domain": {
            "type": "string",
            "description": "Analysis domain: infrastructure, security, or performance"
          },
          "user_level": {
            "type": "string",
            "default": "beginner",
            "description": "User expertise level: beginner, intermediate, or expert"
          }
        }
      }
    }
  }
}
```

This dramatically improves LLM chain success rates!

## Prompt Template Features

### File-Based Templates

Use `file://` prefix to load templates from files:

```python
@mesh.llm(
    system_prompt="file://prompts/analyst.jinja2",  # Relative path
    # OR
    system_prompt="file:///absolute/path/to/template.jinja2"  # Absolute path
)
```

Templates are cached after first load for performance.

### Context Detection

MCP Mesh auto-detects context parameters using:

1. **Explicit** (recommended): `context_param="ctx"`
2. **Convention**: Parameters named `prompt_context`, `llm_context`, or `ctx`
3. **Type hint**: Any parameter typed as `MeshContextModel` subclass

```python
# Explicit - recommended for clarity
@mesh.llm(system_prompt="file://prompts/chat.jinja2", context_param="my_ctx")
def chat(msg: str, my_ctx: dict, llm=None): ...

# Convention - auto-detected
@mesh.llm(system_prompt="file://prompts/chat.jinja2")
def chat(msg: str, ctx: dict, llm=None): ...  # "ctx" detected

# Type hint - auto-detected
@mesh.llm(system_prompt="file://prompts/chat.jinja2")
def chat(msg: str, analysis_ctx: AnalysisContext, llm=None): ...  # MeshContextModel detected
```

### Jinja2 Template Features

Full Jinja2 support including:

**Variables:**

```jinja2
Hello {{ user_name }}! You are in {{ domain }} domain.
```

**Conditionals:**

```jinja2
{% if user_level == "expert" %}
Be concise and technical.
{% else %}
Explain concepts in simple terms.
{% endif %}
```

**Loops:**

```jinja2
Focus on these areas:
{% for area in focus_areas %}
  - {{ area }}
{% endfor %}
```

**Filters:**

```jinja2
{{ capabilities | join(", ") }}
{{ task_type | upper }}
```

### Context Types

Three context types are supported:

```python
# 1. MeshContextModel (recommended - type safe)
@mesh.llm(system_prompt="file://prompts/chat.jinja2")
async def chat(msg: str, ctx: ChatContext, llm=None):
    # ctx validated by Pydantic
    pass

# 2. Dict (flexible)
@mesh.llm(system_prompt="file://prompts/chat.jinja2", context_param="ctx")
async def chat(msg: str, ctx: dict, llm=None):
    # ctx used directly
    pass

# 3. None (static template)
@mesh.llm(system_prompt="file://prompts/static.jinja2")
async def chat(msg: str, llm=None):
    # Template rendered with empty dict {}
    pass
```

## Complete Example: Multi-LLM System

```python
import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Multi-LLM Service")

# 1. Context models
class DocumentContext(MeshContextModel):
    doc_type: str = Field(..., description="Document type: technical, business, legal")
    audience: str = Field(..., description="Target audience: engineer, executive, lawyer")
    max_length: int = Field(default=1000, description="Max output length")

# 2. Specialist LLM - Document Analyzer
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/document_analyzer.jinja2",
    context_param="ctx",
    filter={"tags": ["document", "ocr"]},  # Gets document tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="document_analysis", tags=["llm", "analysis"])
async def analyze_document(
    document: str,
    ctx: DocumentContext,
    llm: mesh.MeshLlmAgent = None
) -> dict:
    return await llm(document)

# 3. Orchestrator LLM - Coordinates specialists
@app.tool()
@mesh.llm(
    system_prompt="You are an orchestrator coordinating document workflows.",
    filter={"capability": "document_analysis"},  # Discovers analyzer
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="document_orchestrator")
async def process_document_workflow(
    task: str,
    llm: mesh.MeshLlmAgent = None
) -> dict:
    # Orchestrator calls specialist with proper context
    return await llm(task)

# 4. Configure agent
@mesh.agent(
    name="multi-llm-service",
    version="1.0.0",
    http_port=8080,
    enable_http=True,
    auto_run=True
)
class MultiLlmAgent:
    pass
```

## Best Practices

### 1. Use Type-Safe Contexts

✅ **Good:**

```python
class AnalysisContext(MeshContextModel):
    domain: str = Field(..., description="Analysis domain")
    user_level: str = Field(default="beginner")

@mesh.llm(system_prompt="file://prompts/analyst.jinja2", context_param="ctx")
def analyze(query: str, ctx: AnalysisContext, llm=None):
    pass
```

❌ **Avoid:**

```python
@mesh.llm(system_prompt="file://prompts/analyst.jinja2")
def analyze(query: str, ctx: dict, llm=None):  # No validation
    pass
```

### 2. Add Field Descriptions

✅ **Good:**

```python
class AnalysisContext(MeshContextModel):
    domain: str = Field(..., description="Analysis domain: infrastructure, security, or performance")
    # Helps LLMs in chains understand valid values
```

❌ **Avoid:**

```python
class AnalysisContext(MeshContextModel):
    domain: str  # No description for LLMs to use
```

### 3. Version Prompts Separately

✅ **Good:**

```python
# prompts/analyst_v1.jinja2
# prompts/analyst_v2.jinja2
@mesh.llm(system_prompt="file://prompts/analyst_v2.jinja2")
```

❌ **Avoid:**

```python
@mesh.llm(system_prompt="You are an analyst. Do X. Do Y. Do Z...")  # Hardcoded
```

### 4. Use Filters for Tool Discovery

✅ **Good:**

```python
@mesh.llm(filter={"tags": ["system", "monitoring"]})  # Discovers tools dynamically
```

❌ **Avoid:**

```python
# Manually listing tools in system prompt
@mesh.llm(system_prompt="You have access to get_cpu, get_memory, get_disk...")
```

### 5. Always Check for None

✅ **Good:**

```python
async def chat(msg: str, llm: mesh.MeshLlmAgent = None):
    if llm is None:
        return "LLM service unavailable"
    return await llm(msg)
```

❌ **Avoid:**

```python
async def chat(msg: str, llm: mesh.MeshLlmAgent = None):
    return await llm(msg)  # Crashes if LLM unavailable
```

## Troubleshooting

### LLM Not Injected (llm is None)

**Cause**: Missing provider configuration or API key

**Solution**:

```bash
export ANTHROPIC_API_KEY=your-api-key
# or
export OPENAI_API_KEY=your-api-key
```

### Template File Not Found

**Cause**: Incorrect path resolution

**Solution**:

```python
# Use absolute path for debugging
@mesh.llm(system_prompt="file:///absolute/path/to/template.jinja2")

# Or ensure relative path is from agent file location
# If agent is in /app/agent.py
# Template should be in /app/prompts/template.jinja2
@mesh.llm(system_prompt="file://prompts/template.jinja2")
```

### Template Rendering Error

**Cause**: Missing variables or syntax errors

**Solution**:

- Check Jinja2 syntax in template
- Ensure all variables in template exist in context
- Use `{% if variable %}` for optional variables

```jinja2
{# Safe template with optional variables #}
Hello {{ user_name | default("Guest") }}!

{% if expertise_level %}
Your level: {{ expertise_level }}
{% endif %}
```

### Context Validation Errors

**Cause**: Missing required fields in MeshContextModel

**Solution**:

```python
# All required fields must be provided
chat(
    "Hello",
    ctx=ChatContext(
        user_name="Alice",  # Required
        domain="tech"       # Required
        # expertise_level optional (has default)
    )
)
```

### Filter Not Finding Tools

**Cause**: No tools match the filter criteria

**Solution**:

```python
# Check tool registration
meshctl list --wide  # See all capabilities and tags

# Broaden filter
@mesh.llm(filter={"tags": ["system"]})  # Instead of specific tags
```

## What's Next?

- **[Advanced Patterns](../02-local-development.md)** - Multi-LLM orchestration
- **[Observability](../07-observability.md)** - Monitor LLM calls and performance
- **[Production Deployment](../04-kubernetes-basics.md)** - Deploy LLM agents to Kubernetes

---

💡 **Pro Tip**: Start with simple LLM injection, then add filters, then templates. Build complexity gradually.

🔐 **Security Note**: Never commit API keys. Use environment variables or secret management.

📊 **Monitoring**: LLM calls are automatically traced - check Grafana dashboards for performance metrics.
