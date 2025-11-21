# LLM Prompt Template Testing with Docker Compose

Quick start guide for testing LLM prompt template features using Docker Compose.

## Overview

The LLM prompt template system enables dynamic, context-aware system prompts with:

- **Jinja2 Templates**: Use `file://` syntax to load template files
- **Type-Safe Contexts**: `MeshContextModel` for validated context objects
- **Auto-Detection**: Automatic context parameter detection via type hints
- **Enhanced Schemas**: Field descriptions for better LLM chains
- **Hot Reload**: Edit templates and code without rebuilding

## Prerequisites

- Docker and Docker Compose installed
- Anthropic API key (get from https://console.anthropic.com/settings/keys)
- At least 4GB RAM available for containers

## Quick Start

### 1. Set API Key

```bash
# Option 1: Export in terminal
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Option 2: Update .env file (recommended)
cd examples/docker-examples
# Edit .env and ensure ANTHROPIC_API_KEY is set
```

### 2. Navigate to Directory

```bash
cd examples/docker-examples
```

### 3. Build Development Images (One-Time)

```bash
docker compose -f docker-compose.prompt-templates.yml build
```

This builds the development image with hot-reload support for the MCP Mesh runtime.

### 4. Start Infrastructure

```bash
docker compose -f docker-compose.prompt-templates.yml up -d postgres redis registry system-agent
```

Wait ~20 seconds for services to start and become healthy.

### 5. Verify Infrastructure

```bash
# Check all services are healthy
docker compose -f docker-compose.prompt-templates.yml ps

# Check registry health
curl -s http://localhost:8002/health | jq

# Check system-agent is registered
curl -s http://localhost:8002/agents | jq '.agents[] | {name, status}'
```

## Running Tests

### Test PT-001: Basic Template with Dict Context

```bash
# Start test agent
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-001 up -d

# Check health
curl -s http://localhost:9011/health | jq

# Test the template
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
        "message": "What can you help me with?",
        "ctx": {
          "user_name": "Alice",
          "language": "friendly"
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# View logs
docker compose -f docker-compose.prompt-templates.yml logs -f test-pt-001-basic-template

# Stop test
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-001 down
```

### Test PT-002: MeshContextModel with Field Descriptions

```bash
# Start test agent
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-002 up -d

# Wait for agent to be healthy
sleep 20

# Test with MeshContextModel
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
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop test
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-002 down
```

### Test PT-003: Convention-Based Context Detection

```bash
# Start test agent
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-003 up -d
sleep 15

# Test 3a: Type hint detection
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

# Test 3b: Convention detection
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

# Stop test
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-003 down
```

### Test PT-004: Control Structures

```bash
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-004 up -d
sleep 20

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

docker compose -f docker-compose.prompt-templates.yml --profile test-pt-004 down
```

### Test PT-005: Hierarchical Context Models

```bash
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-005 up -d
sleep 20

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
        "request": "Perform system cleanup and optimization",
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

docker compose -f docker-compose.prompt-templates.yml --profile test-pt-005 down
```

### Test PT-006: LLM Chain with Enhanced Schemas

```bash
# Start both analyzer and orchestrator
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-006 up -d

# Wait for both agents to be healthy
sleep 30

# Verify analyzer schema has Field descriptions
curl -s http://localhost:9016/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq '.result.tools[0].inputSchema.properties.ctx'

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

# View logs from both layers
docker compose -f docker-compose.prompt-templates.yml logs test-pt-006-orchestrator test-pt-006-analyzer

# Stop test
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-006 down
```

## Development Workflow

### Editing Runtime Code (Hot Reload)

The development setup mounts the runtime source code, so you can edit and test without rebuilding:

```bash
# 1. Edit runtime code
vim ../../src/runtime/python/_mcp_mesh/engine/mesh_llm_agent.py

# 2. Restart the container (NO rebuild needed!)
docker compose -f docker-compose.prompt-templates.yml restart test-pt-001-basic-template

# 3. Test immediately - changes are live!
curl -X POST http://localhost:9011/mcp ...
```

### Editing Template Files

Template files are also mounted, so changes take effect immediately:

```bash
# 1. Edit template
vim ../llm-examples/prompt-templates/prompts/basic_chat.jinja2

# 2. Restart container (template cache cleared on restart)
docker compose -f docker-compose.prompt-templates.yml restart test-pt-001-basic-template

# 3. Test with new template
curl -X POST http://localhost:9011/mcp ...
```

### Editing Agent Code

```bash
# 1. Edit agent code
vim ../llm-examples/prompt-templates/test_001_basic_template.py

# 2. Restart container
docker compose -f docker-compose.prompt-templates.yml restart test-pt-001-basic-template
```

## Useful Commands

### View All Running Containers

```bash
docker compose -f docker-compose.prompt-templates.yml ps
```

### View Logs

```bash
# All services
docker compose -f docker-compose.prompt-templates.yml logs -f

# Specific service
docker compose -f docker-compose.prompt-templates.yml logs -f test-pt-001-basic-template

# Filter logs
docker compose -f docker-compose.prompt-templates.yml logs test-pt-001-basic-template | grep -i "template\|context"
```

### Check Registry Agents

```bash
curl -s http://localhost:8002/agents | jq '.agents[] | {name, status, capabilities: (.capabilities | length)}'
```

### Exec into Container

```bash
docker compose -f docker-compose.prompt-templates.yml exec test-pt-001-basic-template bash
```

### Database Access

```bash
# Connect to PostgreSQL
docker exec -it mcp-mesh-postgres-prompt-template-test psql -U mcpmesh -d mcpmesh

# Inside psql:
# SELECT * FROM agents;
# SELECT name, capability FROM capabilities WHERE name LIKE '%template%';
```

## Cleanup

### Stop Test Agent (Keep Infrastructure)

```bash
docker compose -f docker-compose.prompt-templates.yml --profile test-pt-001 down
```

### Stop Everything

```bash
docker compose -f docker-compose.prompt-templates.yml down
```

### Full Cleanup (Remove Volumes)

```bash
docker compose -f docker-compose.prompt-templates.yml down -v
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose -f docker-compose.prompt-templates.yml logs <service-name>

# Check if API key is set
echo $ANTHROPIC_API_KEY
```

### Template Not Found

```bash
# Check template file exists
ls ../llm-examples/prompt-templates/prompts/

# Check volume mount in logs
docker compose -f docker-compose.prompt-templates.yml logs <service-name> | grep prompts
```

### Agent Not Registered

```bash
# Check agent logs for registration
docker compose -f docker-compose.prompt-templates.yml logs <service-name> | grep -i "register\|heartbeat"

# Check registry logs
docker compose -f docker-compose.prompt-templates.yml logs registry | grep -i "agent"
```

### Reset Everything

```bash
# Stop all services
docker compose -f docker-compose.prompt-templates.yml down -v

# Rebuild from scratch
docker compose -f docker-compose.prompt-templates.yml build --no-cache

# Start fresh
docker compose -f docker-compose.prompt-templates.yml up -d postgres redis registry system-agent
```

## Port Reference

| Service                  | Port | Description           |
| ------------------------ | ---- | --------------------- |
| Registry                 | 8002 | Registry API          |
| PostgreSQL               | 5434 | Database              |
| Redis                    | 6381 | Tracing/Sessions      |
| System Agent             | 8084 | Base tools            |
| Test PT-001              | 9011 | Basic template        |
| Test PT-002              | 9012 | Context model         |
| Test PT-003              | 9013 | Convention detection  |
| Test PT-004              | 9014 | Control structures    |
| Test PT-005              | 9015 | Hierarchical contexts |
| Test PT-006 Analyzer     | 9016 | Document analyzer     |
| Test PT-006 Orchestrator | 9017 | Orchestrator          |

## Next Steps

For complete documentation and examples, see: `../prompt-template-examples/README.md`

## Features Tested

- ✅ Basic template rendering with `file://` syntax
- ✅ Dict context injection
- ✅ MeshContextModel type-safe contexts
- ✅ Pydantic Field descriptions in schemas
- ✅ Type hint-based context detection
- ✅ Convention-based context detection
- ✅ Jinja2 control structures (if/for/filters)
- ✅ Hierarchical/nested context models
- ✅ Enhanced schemas for LLM chains
- ✅ Template hot reload during development
