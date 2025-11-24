# LLM Mesh Delegation Examples

Examples demonstrating LLM mesh delegation - distributing LLM calls across the mesh network.

## What is LLM Mesh Delegation?

Instead of making LLM calls directly via LiteLLM, delegate them to mesh-registered LLM provider agents:

- **Provider Side**: `@mesh.llm_provider` creates zero-code LLM agents
- **Consumer Side**: `@mesh.llm(provider=dict)` discovers and calls providers via mesh DI
- **Benefits**: Centralized LLM management, cost optimization, geographic routing, failover

## Quick Start

### Prerequisites

```bash
# Verify docker-compose file exists
ls ../docker-examples/docker-compose.llm-delegation.yml

# Check API key is set
grep ANTHROPIC_API_KEY ../docker-examples/.env
```

### Start Infrastructure

```bash
cd ../docker-examples

# Start infrastructure (registry auto-starts)
docker compose -f docker-compose.llm-delegation.yml up -d postgres redis registry

# Wait for services to be healthy
sleep 20

# Verify
docker compose -f docker-compose.llm-delegation.yml ps
curl -s http://localhost:8002/health | jq
```

## Examples

### PT-008: LLM Provider Registration

**Concept**: Verify `@mesh.llm_provider` registers correctly as MCP tool and mesh agent.

```bash
# Start
docker compose -f docker-compose.llm-delegation.yml --profile test-pt-008 up -d
sleep 15

# Check provider registered in mesh network
curl -s http://localhost:8002/agents | jq '.[] | select(.name | contains("llm-provider"))'

# List MCP tools (should see process_chat)
curl -s http://localhost:9019/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools'

# Test direct MCP call
curl -X POST http://localhost:9019/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "process_chat",
      "arguments": {
        "request": {
          "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello in exactly 5 words."}
          ]
        }
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Stop
docker compose -f docker-compose.llm-delegation.yml --profile test-pt-008 down
```

### PT-009: Basic Mesh Delegation

**Concept**: Consumer uses `@mesh.llm(provider=dict)` to call provider via mesh.

```bash
# Start both provider and consumer
docker compose -f docker-compose.llm-delegation.yml --profile test-pt-009 up -d
sleep 20

# Check both agents registered
curl -s http://localhost:8002/agents | jq '.agents[] | select(.name | contains("pt-009"))'

# Call consumer (which delegates to provider via mesh)
curl -X POST http://localhost:9021/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "ask_question",
      "arguments": {
        "question": "What is 2+2? Answer in exactly 2 words."
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Check consumer logs to verify mesh delegation
docker logs mcp-mesh-test-pt-009-consumer 2>&1 | grep -i "mesh provider"

# Check provider logs to verify it received the request
docker logs mcp-mesh-test-pt-009-provider 2>&1 | grep -i "processed request"

# Stop
docker compose -f docker-compose.llm-delegation.yml --profile test-pt-009 down
```

## Port Reference

| Service         | Port | Description                       |
| --------------- | ---- | --------------------------------- |
| Registry        | 8002 | Registry API                      |
| PostgreSQL      | 5434 | Database                          |
| Redis           | 6381 | Tracing/Sessions                  |
| PT-008 Provider | 9019 | LLM provider registration test    |
| PT-009 Provider | 9020 | LLM provider for mesh delegation  |
| PT-009 Consumer | 9021 | Consumer using mesh-delegated LLM |

## Troubleshooting

### Provider Not Found

**Error**: `MeshDependencyNotFound: No LLM provider found`

**Solutions**:

- Check provider is running: `docker compose -f docker-compose.llm-delegation.yml ps`
- Verify registration: `curl http://localhost:8002/agents | jq`
- Check tags match: Consumer `tags: ["claude"]` should match provider

### LiteLLM API Error

**Error**: `litellm.AuthenticationError: API key not found`

**Solution**: Set API key in `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

### Model Not Found

**Error**: `litellm.NotFoundError: model not found`

**Solution**: Use vendor-prefixed model names:

- ✅ `model="anthropic/claude-sonnet-4-5"`
- ❌ `model="claude-3-5-sonnet-20241022"`

## Cleanup

```bash
# Stop all tests
docker compose -f docker-compose.llm-delegation.yml down

# Full cleanup (remove volumes)
docker compose -f docker-compose.llm-delegation.yml down -v
```

## Learn More

See [LLM Dependency Injection](../../docs/03-core-features/05-llm-dependency-injection.md) for complete documentation.
