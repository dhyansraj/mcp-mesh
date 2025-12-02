# Testing MCP Agents

> How to test MCP Mesh agents using curl and the MCP JSON-RPC protocol

## Overview

MCP agents expose a JSON-RPC 2.0 API over HTTP with Server-Sent Events (SSE) responses. This guide shows the correct curl syntax for testing agents - a common source of errors when working with MCP.

## Key Points

- **Endpoint**: Always POST to `/mcp` (not REST-style paths like `/tools/list`)
- **Method**: Always `POST`
- **Headers**: Must include both `Content-Type` AND `Accept` headers
- **Body**: JSON-RPC 2.0 format with `jsonrpc`, `id`, `method`, `params`
- **Response**: Server-Sent Events format, requires parsing

## List Available Tools

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

## Call a Tool (No Arguments)

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_time",
      "arguments": {}
    }
  }'
```

## Call a Tool (With Arguments)

```bash
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {"title": "Test Report", "format": "markdown"}
    }
  }'
```

## Available MCP Methods

| Method           | Description                  |
| ---------------- | ---------------------------- |
| `tools/list`     | List all available tools     |
| `tools/call`     | Invoke a tool with arguments |
| `prompts/list`   | List available prompts       |
| `resources/list` | List available resources     |
| `resources/read` | Read a resource              |

## Response Format

MCP responses use Server-Sent Events (SSE) format:

```
data: {"jsonrpc":"2.0","id":1,"result":{"tools":[...]}}
```

To parse the response, you can pipe through:

```bash
| grep "^data:" | sed 's/^data: //' | jq .
```

## Common Errors

### Missing Accept Header

```
Error: Response not in expected format
Fix: Add -H "Accept: application/json, text/event-stream"
```

### Wrong Endpoint

```
Error: 404 Not Found
Fix: Use /mcp endpoint, not /tools/list or similar
```

### Invalid JSON-RPC Format

```
Error: Invalid request
Fix: Ensure body has jsonrpc, id, method, and params fields
```

## Testing with meshctl

```bash
# Find agent ports
meshctl list

# Check agent status
meshctl status --verbose
```

## See Also

- `meshctl man decorators` - How to create tools
- `meshctl man capabilities` - Understanding capabilities
