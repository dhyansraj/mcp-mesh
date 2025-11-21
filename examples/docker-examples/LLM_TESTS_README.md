# LLM Integration Testing with Docker Compose

Quick start guide for running LLM integration tests using Docker Compose.

## Prerequisites

- Docker and Docker Compose installed
- Anthropic API key (get from https://console.anthropic.com/settings/keys)
- At least 4GB RAM available for containers

## Quick Start

### 1. Set API Key

```bash
# Option 1: Export in terminal
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Option 2: Create .env file (recommended)
cp .env.example .env
# Edit .env and add your API key
```

### 2. Navigate to Directory

```bash
cd examples/docker-examples
```

### 3. Build Development Images (One-Time)

```bash
docker compose -f docker-compose.llm-tests.yml build
```

This builds the development image with hot-reload support for the MCP Mesh runtime.

### 4. Start Infrastructure

```bash
docker compose -f docker-compose.llm-tests.yml up -d postgres redis registry system-agent
```

Wait ~20 seconds for services to start and become healthy.

### 5. Verify Infrastructure

```bash
# Check all services are healthy
docker compose -f docker-compose.llm-tests.yml ps

# Check registry health
curl -s http://localhost:8000/health | jq

# Check system-agent is registered
curl -s http://localhost:8000/agents | jq '.agents[] | {name, status}'
```

## Running Tests

### Test 1: Basic LLM (No Tools)

```bash
# Start test agent
docker compose -f docker-compose.llm-tests.yml --profile test-001 up -d

# Check health
curl -s http://localhost:9001/health | jq

# Test the LLM
curl -X POST http://localhost:9001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat",
      "arguments": {
        "message": "What is 2+2?"
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text' -r | jq

# View logs
docker compose -f docker-compose.llm-tests.yml logs -f test-001-basic-llm

# Stop test
docker compose -f docker-compose.llm-tests.yml --profile test-001 down
```

### Test 2: LLM with Time Tools

```bash
# Start test agent
docker compose -f docker-compose.llm-tests.yml --profile test-002 up -d

# Test with time question
curl -X POST http://localhost:9002/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat",
      "arguments": {
        "message": "What is the current time?"
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text' -r | jq

# Stop test
docker compose -f docker-compose.llm-tests.yml --profile test-002 down
```

### Test 3: Multi-Tool LLM

```bash
# Start test agent
docker compose -f docker-compose.llm-tests.yml --profile test-003 up -d

# Test with comprehensive question
curl -X POST http://localhost:9003/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "chat",
      "arguments": {
        "message": "Give me a complete system status report including current time, uptime, and system information."
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text' -r | jq

# Stop test
docker compose -f docker-compose.llm-tests.yml --profile test-003 down
```

### Test 4: Hierarchical LLM Composition

```bash
# Start both analyst and orchestrator
docker compose -f docker-compose.llm-tests.yml --profile test-004 up -d

# Wait for both agents to be healthy
sleep 30

# Test orchestrator (calls analyst which calls system-agent)
curl -X POST http://localhost:9005/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "orchestrate",
      "arguments": {
        "task": "I need a comprehensive system report. Please consult the appropriate specialists."
      }
    }
  }' 2>&1 | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text' -r | jq

# View logs from all layers
docker compose -f docker-compose.llm-tests.yml logs test-004-orchestrator test-004-analyst system-agent

# Stop test
docker compose -f docker-compose.llm-tests.yml --profile test-004 down
```

## Development Workflow

### Editing Runtime Code (Hot Reload)

The development setup mounts the runtime source code, so you can edit and test without rebuilding:

```bash
# 1. Edit runtime code
vim ../../src/runtime/python/_mcp_mesh/engine/mesh_llm_agent.py

# 2. Restart the container (NO rebuild needed!)
docker compose -f docker-compose.llm-tests.yml restart test-001-basic-llm

# 3. Test immediately - changes are live!
curl -X POST http://localhost:9001/mcp ...
```

### Editing Agent Code

Agent files are also mounted, so changes take effect on restart:

```bash
# 1. Edit agent code
vim ../llm-examples/test_001_basic_llm_agent.py

# 2. Restart container
docker compose -f docker-compose.llm-tests.yml restart test-001-basic-llm
```

## Useful Commands

### View All Running Containers

```bash
docker compose -f docker-compose.llm-tests.yml ps
```

### View Logs

```bash
# All services
docker compose -f docker-compose.llm-tests.yml logs -f

# Specific service
docker compose -f docker-compose.llm-tests.yml logs -f test-001-basic-llm

# Filter logs
docker compose -f docker-compose.llm-tests.yml logs test-001-basic-llm | grep -i "llm\|tool\|error"
```

### Check Registry Agents

```bash
curl -s http://localhost:8000/agents | jq '.agents[] | {name, status, capabilities: (.capabilities | length)}'
```

### Exec into Container

```bash
docker compose -f docker-compose.llm-tests.yml exec test-001-basic-llm bash
```

### Database Access

```bash
# Connect to PostgreSQL
docker exec -it mcp-mesh-postgres-llm-test psql -U mcpmesh -d mcpmesh

# Inside psql:
# SELECT * FROM agents;
# SELECT name, capability, llm_filter FROM capabilities WHERE llm_filter IS NOT NULL;
```

### Redis Access

```bash
# Check trace data
docker exec -it mcp-mesh-redis-llm-test redis-cli XREVRANGE mesh:trace + - COUNT 10
```

## Cleanup

### Stop Test Agent (Keep Infrastructure)

```bash
docker compose -f docker-compose.llm-tests.yml --profile test-001 down
```

### Stop Everything

```bash
docker compose -f docker-compose.llm-tests.yml down
```

### Full Cleanup (Remove Volumes)

```bash
docker compose -f docker-compose.llm-tests.yml down -v
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose -f docker-compose.llm-tests.yml logs <service-name>

# Check if API key is set
echo $ANTHROPIC_API_KEY
```

### Agent Not Registered

```bash
# Check agent logs for registration
docker compose -f docker-compose.llm-tests.yml logs <service-name> | grep -i "register\|heartbeat"

# Check registry logs
docker compose -f docker-compose.llm-tests.yml logs registry | grep -i "agent"
```

### Tools Not Discovered

```bash
# Check if system-agent is healthy
curl http://localhost:8000/agents | jq '.agents[] | select(.name=="system-agent")'

# Check test agent logs for llm_tools
docker compose -f docker-compose.llm-tests.yml logs <service-name> | grep -i "llm_tools"
```

### Reset Everything

```bash
# Stop all services
docker compose -f docker-compose.llm-tests.yml down -v

# Rebuild from scratch
docker compose -f docker-compose.llm-tests.yml build --no-cache

# Start fresh
docker compose -f docker-compose.llm-tests.yml up -d postgres redis registry system-agent
```

## Port Reference

| Service             | Port | Description      |
| ------------------- | ---- | ---------------- |
| Registry            | 8000 | Registry API     |
| PostgreSQL          | 5432 | Database         |
| Redis               | 6379 | Tracing/Sessions |
| System Agent        | 8082 | Base tools       |
| Test 1              | 9001 | Basic LLM        |
| Test 2              | 9002 | LLM with time    |
| Test 3              | 9003 | Multi-tool LLM   |
| Test 4 Analyst      | 9004 | Specialist LLM   |
| Test 4 Orchestrator | 9005 | Coordinator LLM  |

## Next Steps

For comprehensive manual testing procedures, see: `../../LLM_DOCKER_COMPOSE_TEST_PLAN.org`
