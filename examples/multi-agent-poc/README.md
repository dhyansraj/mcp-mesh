# Multi-Agent Proof of Concept

This example demonstrates MCP Mesh's **LLM Provider as Dependencies** pattern, showcasing automatic failover between different LLM providers (Claude, OpenAI) in a multi-agent system.

## What This Does

This POC sets up a complete multi-agent system with:

- **Registry**: Central service discovery and health monitoring
- **Intent Agent**: Orchestrates conversations and delegates to specialist agents
- **Code Executor**: Specialist agent that executes Python code
- **File Manager**: Specialist agent that manages files
- **Claude Provider**: LLM provider wrapping Anthropic's Claude
- **OpenAI Provider**: LLM provider wrapping OpenAI's GPT models

The key feature is **automatic LLM provider failover**: if Claude is unavailable, the Intent Agent automatically switches to OpenAI without any code changes.

## Prerequisites

- Docker and Docker Compose
- API keys for Claude and/or OpenAI (set via environment variables)
- `meshctl` CLI tool (built from `src/meshctl`)

## Quick Start

### 1. Start the Services

```bash
# From the examples/multi-agent-poc directory
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml up -d
```

This starts all 6 services:

- `registry` on port 8003
- `intent-agent` on port 9200
- `code-executor` on port 9201
- `file-manager` on port 9202
- `claude-provider` on port 9101
- `openai-provider` on port 9102

### 2. Verify All Agents Are Running

```bash
# Check healthy agents
meshctl list --registry-port 8003 --healthy-only

# Expected output:
# AGENT ID                        NAME                      TYPE        STATUS    VERSION   HOST           PORT
# intent-service-XXXXX            intent-service-XXXXX      mcp-agent   healthy   1.0.0     10.x.x.x       9200
# code-executor-XXXXX             code-executor-XXXXX       mcp-agent   healthy   1.0.0     10.x.x.x       9201
# file-manager-XXXXX              file-manager-XXXXX        mcp-agent   healthy   1.0.0     10.x.x.x       9202
# claude-provider-XXXXX           claude-provider-XXXXX     mcp-agent   healthy   1.0.0     10.x.x.x       9101
# openai-provider-XXXXX           openai-provider-XXXXX     mcp-agent   healthy   1.0.0     10.x.x.x       9102
```

## Testing the System

### Basic Test - Prime Number Generation

Create a test payload file:

```bash
cat > test-prime-request.json << 'EOF'
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "messages": [
        {"role": "user", "content": "Hi! I need help with a Python script."},
        {"role": "assistant", "content": "{\"message\": \"Hi there! I'd be happy to help you with your Python script. \\n\\nCould you tell me a bit more about what you need? For example:\\n- Are you looking to create a new Python script from scratch?\\n- Do you need help modifying or debugging an existing script?\\n- What should the script do? What problem are you trying to solve?\\n\\nThe more details you can share about what you're working on, the better I can assist you!\", \"action_taken\": \"Asked clarifying questions to understand the user's needs\", \"specialist_used\": null, \"specialist_response\": null}"},
        {"role": "user", "content": "I need a Python script that calculates prime numbers up to a given limit. Can you create one for me?"}
      ]
    }
  }
}
EOF
```

Send the request:

```bash
# Using meshctl (reads JSON arguments from file)
meshctl call --registry http://localhost:8003 --agent-url http://localhost:9200 chat "$(cat test-prime-request.json | jq -c '.params.arguments')"

# Or using curl directly
curl -s -X POST http://localhost:9200/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d @test-prime-request.json | jq
```

Expected behavior:

- Intent Agent receives the request
- Intent Agent resolves `["+claude"]` dependency → finds Claude Provider
- Claude Provider generates comprehensive Python code with tests and documentation
- Code Executor runs the code
- File Manager saves the files
- Response returned with all created files

Check the generated files:

```bash
ls -la workspace/
# Should see: prime_calculator.py, test_prime_calculator.py, README.md, etc.
```

## Testing Automatic Failover

### Scenario: Claude Provider Failure → OpenAI Takeover

1. **Stop Claude Provider** to simulate failure:

```bash
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml stop claude-provider
```

2. **Verify Claude is Down**:

```bash
meshctl list --registry-port 8003
# Claude provider should show as unhealthy or missing
```

3. **Send the Same Request Again**:

```bash
# Using meshctl
meshctl call --registry http://localhost:8003 --agent-url http://localhost:9200 chat "$(cat test-prime-request.json | jq -c '.params.arguments')"

# Or using curl
curl -s -X POST http://localhost:9200/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d @test-prime-request.json | jq
```

Expected behavior:

- Intent Agent tries to resolve `["+claude"]` dependency
- Claude Provider is unhealthy/unavailable
- **Automatic failover**: Intent Agent falls back to OpenAI Provider
- OpenAI Provider generates the Python code (simpler but functional)
- Code still executes and files are created

4. **Restart Claude Provider**:

```bash
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml start claude-provider

# Wait for it to register (5-10 seconds)
meshctl list --registry-port 8003 --healthy-only
```

5. **Next Request Uses Claude Again** (automatic recovery):

```bash
# Using meshctl
meshctl call --registry http://localhost:8003 --agent-url http://localhost:9200 chat "$(cat test-prime-request.json | jq -c '.params.arguments')"

# Or using curl
curl -s -X POST http://localhost:9200/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d @test-prime-request.json | jq
```

## Monitoring and Debugging

### View Agent Logs

```bash
# All services
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml logs -f

# Specific service
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml logs -f intent-agent
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml logs -f claude-provider
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml logs -f openai-provider
```

### Check Agent Dependencies

```bash
# Show which LLM provider each agent is using
meshctl list --registry-port 8003 --show-dependencies
```

### Registry Health

```bash
# Check registry API
curl http://localhost:8003/health

# List all agents (including unhealthy)
curl http://localhost:8003/api/v1/agents | jq
```

## Cleanup

```bash
# Stop all services
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml down

# Remove volumes (clears workspace files)
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml down -v

# Clean up generated files
rm -rf workspace/*
```

## Architecture Highlights

### Zero-Code LLM Provider Pattern

Both Claude and OpenAI providers are implemented with ~15 lines of actual code:

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["llm", "claude", "anthropic", "sonnet", "provider"],
    version="1.0.0",
)
def claude_provider():
    """Zero-code Claude LLM provider"""
    pass  # Implementation is in the decorator
```

### Dependency Resolution

Intent Agent declares LLM dependency using preference tags:

```python
@mesh.llm(
    capability="llm",
    description="LLM for intent understanding",
    tags=["+claude"],  # Prefer Claude, but accept any LLM if unavailable
)
```

The registry automatically:

1. Finds providers matching `capability="llm"`
2. Scores them based on tag overlap (`+claude` gives Claude higher score)
3. Returns the best available provider
4. Falls back to alternatives if primary is unhealthy

### Fault Isolation

Each component runs as an independent microservice:

- Claude failure doesn't affect OpenAI
- Code Executor failure doesn't affect File Manager
- Intent Agent can retry with different providers
- Registry monitors health and automatically removes failed agents

## Comparing Claude vs OpenAI

Run the same request with both providers to see the difference:

| Aspect            | Claude (Sonnet 4.5)                | OpenAI (GPT-4)                 |
| ----------------- | ---------------------------------- | ------------------------------ |
| **Code Quality**  | Comprehensive, production-ready    | Functional, straightforward    |
| **Lines of Code** | ~127 lines with docs/tests         | ~41 lines basic implementation |
| **Algorithm**     | Sieve of Eratosthenes (optimal)    | Trial division (simple)        |
| **Documentation** | Detailed README, docstrings        | Basic docstrings               |
| **Test Coverage** | Separate test file with edge cases | No tests                       |
| **CLI Features**  | Argument parsing, formatted output | Input prompt only              |

## Troubleshooting

**Problem**: Agents not appearing in `meshctl list`

**Solution**: Wait 5-10 seconds for initial registration, check logs for connection errors

---

**Problem**: `curl` request times out

**Solution**: Verify intent-agent is running on port 9200:

```bash
docker-compose -f ../docker-examples/docker-compose.multi-agent-poc.yml ps intent-agent
```

---

**Problem**: Both Claude and OpenAI fail

**Solution**: Check API keys are set correctly in docker-compose environment variables

---

**Problem**: Files not created in workspace

**Solution**: Check code-executor and file-manager logs for errors

## Learn More

- [MCP Mesh Documentation](https://dhyansraj.github.io/mcp-mesh/)
- [LLM Provider Pattern](../../MEDIUM-POST-MULTI-AGENT-POC.md)
- [GitHub Repository](https://github.com/dhyansraj/mcp-mesh)
