# MCP Mesh Prompt Template Examples

Examples demonstrating LLM prompt templates with dynamic context injection using MCP Mesh.

## What Are Prompt Templates?

The LLM prompt template system enables dynamic, context-aware system prompts:

- **Jinja2 templates** with `file://` syntax
- **Type-safe contexts** using `MeshContextModel`
- **Automatic context detection** via type hints
- **Field descriptions** for enhanced schemas
- **Runtime template rendering** with context injection

## Quick Start

### Prerequisites

```bash
# Verify files exist
ls ../docker-examples/docker-compose.prompt-templates.yml
ls ../docker-examples/.env  # Should have ANTHROPIC_API_KEY

# Check API key is set
grep ANTHROPIC_API_KEY ../docker-examples/.env
```

### Start Infrastructure

```bash
cd ../docker-examples

# Build development images (one-time)
docker compose -f docker-compose.prompt-templates.yml build

# Start infrastructure (registry auto-starts)
docker compose -f docker-compose.prompt-templates.yml up -d postgres redis registry system-agent

# Wait for services to be healthy
sleep 20

# Verify
docker compose -f docker-compose.prompt-templates.yml ps
curl -s http://localhost:8002/health | jq
```

## Examples

### PT-001: Basic Template with Dict Context

**Concept**: Template file resolution and dict context rendering.

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-001 up -d
sleep 15

# Test
curl -X POST http://localhost:9011/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat",
      "arguments": {
        "message": "Hello! How can you help me?",
        "ctx": {
          "user_name": "Alice",
          "language": "friendly"
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-001 down
```

### PT-002: MeshContextModel with Field Descriptions

**Concept**: Type-safe Pydantic models with field descriptions for enhanced schemas.

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-002 up -d
sleep 20

# Test
curl -X POST http://localhost:9012/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "analyze_system",
      "arguments": {
        "query": "Check overall system health",
        "analysis_ctx": {
          "domain": "infrastructure",
          "user_level": "expert",
          "max_tools": 10,
          "focus_areas": ["memory", "disk", "cpu"]
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text' | head -30

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-002 down
```

### PT-003: Convention-Based Context Detection

**Concept**: Automatic context parameter detection without explicit `context_param`.

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-003 up -d
sleep 15

# Test type hint detection
curl -X POST http://localhost:9013/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat_type_hint",
      "arguments": {
        "message": "Explain async/await",
        "ctx": {
          "user_name": "Bob",
          "domain": "Python programming",
          "tone": "professional",
          "style": "technical"
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Test convention name detection
curl -X POST http://localhost:9013/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat_convention",
      "arguments": {
        "message": "Explain generators",
        "prompt_context": {
          "user_name": "Carol",
          "domain": "Python",
          "tone": "casual",
          "style": "simple"
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-003 down
```

### PT-004: Control Structures

**Concept**: Advanced Jinja2 features (conditionals, loops, filters).

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-004 up -d
sleep 20

# Test
curl -X POST http://localhost:9014/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "orchestrate",
      "arguments": {
        "request": "Analyze system health",
        "ctx": {
          "task_type": "system_analysis",
          "priority": "high",
          "capabilities": ["monitoring", "diagnostics", "reporting"],
          "constraints": ["Complete within 5 minutes", "Use read-only operations"]
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-004 down
```

### PT-005: Hierarchical Context Models

**Concept**: Nested `MeshContextModel` structures with deep property access.

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-005 up -d
sleep 20

# Test
curl -X POST http://localhost:9015/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "execute_task",
      "arguments": {
        "request": "Perform system cleanup",
        "task": {
          "user": {
            "name": "Alice Johnson",
            "role": "admin",
            "permissions": ["read", "write", "execute", "admin"]
          },
          "task_type": "system_maintenance",
          "priority": "high",
          "deadline": "2025-01-20"
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-005 down
```

### PT-006: LLM Chain with Enhanced Schemas

**Concept**: Field descriptions flow to calling LLMs in hierarchical chains.

```bash
# Start both analyzer and orchestrator
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-006 up -d
sleep 30

# Verify analyzer schema has Field descriptions
curl -s http://localhost:9016/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq '.result.tools[0].inputSchema'

# Test orchestrator calling analyzer
curl -X POST http://localhost:9017/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "orchestrate_analysis",
      "arguments": {
        "request": "Analyze this contract for Alice, focus on key obligations"
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-006 down
```

### PT-007: Dual Injection (LLM + MCP Agent)

**Concept**: Inject both `MeshLlmAgent` and `McpMeshAgent` into the same function.

```bash
# Start
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-007 up -d
sleep 20

# Test
curl -X POST http://localhost:9018/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "analyze_with_enrichment",
      "arguments": {
        "query": "Analyze system performance trends"
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-007 down
```

## Port Reference

| Service             | Port | Description           |
| ------------------- | ---- | --------------------- |
| Registry            | 8002 | Registry API          |
| PostgreSQL          | 5434 | Database              |
| Redis               | 6381 | Tracing/Sessions      |
| System Agent        | 8084 | Base tools            |
| PT-001              | 9011 | Basic template        |
| PT-002              | 9012 | Context model         |
| PT-003              | 9013 | Convention detection  |
| PT-004              | 9014 | Control structures    |
| PT-005              | 9015 | Hierarchical contexts |
| PT-006 Analyzer     | 9016 | Document analyzer     |
| PT-006 Orchestrator | 9017 | Orchestrator          |
| PT-007              | 9018 | Dual injection        |

## Troubleshooting

### Template Not Found

**Error**: `FileNotFoundError: Template file not found`

**Solutions**:

- Verify `prompts/` directory mounted in container
- Check Docker volume mount in compose file

### Template Syntax Error

**Error**: `TemplateSyntaxError: unexpected '}'`

**Solutions**:

- Validate matching braces: `{{ }}`, `{% %}`, `{# #}`
- Test template locally with Jinja2

### Model Not Found

**Error**: `litellm.NotFoundError: model: claude-3-5-sonnet-20241022`

**Solution**: Use vendor-prefixed model names:

- ✅ `model="anthropic/claude-sonnet-4-5"`
- ❌ `model="claude-3-5-sonnet-20241022"`

## Cleanup

```bash
# Stop all tests
docker compose -f docker-compose.prompt-templates.yml down

# Full cleanup (remove volumes)
docker compose -f docker-compose.prompt-templates.yml down -v

# Reset everything
docker compose -f docker-compose.prompt-templates.yml down -v
docker compose -f docker-compose.prompt-templates.yml build --no-cache
docker compose -f docker-compose.prompt-templates.yml up -d postgres redis registry system-agent
```

## Learn More

See [LLM Integration Tutorial](../../docs/01-getting-started/06-llm-integration.md) for complete documentation on prompt templates and LLM dependency injection.
