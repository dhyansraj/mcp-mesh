# HTTP Header Propagation (TypeScript)

> Forward custom HTTP headers across agent-to-agent calls

## Overview

MCP Mesh can propagate user-defined HTTP headers through the call chain.
When Agent A calls Agent B, configured headers from the incoming request
are automatically forwarded. This enables auth token forwarding, correlation
IDs, tenant context, and any custom metadata — without coupling agents to
a specific auth or observability framework.

## Configuration

Set the allowlist via environment variable on every agent in the chain:

```bash
export MCP_MESH_PROPAGATE_HEADERS=authorization,x-request-id,x-tenant-id
```

- Comma-separated header name **prefixes**
- Case-insensitive (normalized to lowercase internally)
- Prefix matching: `x-audit` matches `x-audit-id`, `x-audit-source`, etc.
- Whitespace around names is trimmed
- Parsed once at startup — restart to change
- Must be set on **every agent** in the chain that should participate

With no value set, no custom headers are propagated. Trace headers
(`X-Trace-ID`, `X-Parent-Span`) are always propagated independently.

## How It Works

```
Client                Agent A              Agent B              Agent C
  │                     │                     │                    │
  │ Authorization: Bxxx │                     │                    │
  │────────────────────>│                     │                    │
  │                     │ captures "authorization" from allowlist  │
  │                     │                     │                    │
  │                     │ Authorization: Bxxx │                    │
  │                     │────────────────────>│                    │
  │                     │                     │ Authorization: Bxxx│
  │                     │                     │───────────────────>│
```

1. Incoming request arrives with headers
2. Agent captures headers matching the allowlist into request-scoped context
3. When the agent calls another agent, captured headers are injected
   into the outgoing HTTP request automatically
4. The downstream agent repeats the process — headers flow end-to-end

TypeScript uses `AsyncLocalStorage` for async-safe, request-scoped storage
so concurrent requests are fully isolated.

## Reading Headers in Tool Handlers

Headers are captured and forwarded automatically. You can also read them
explicitly in your tool code:

```typescript
import { getCurrentPropagatedHeaders } from "@mcpmesh/sdk";

agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  parameters: z.object({ name: z.string() }),
  execute: async ({ name }) => {
    const headers = getCurrentPropagatedHeaders();
    const tenant = headers["x-tenant-id"] ?? "unknown";
    return JSON.stringify({ user: name, tenant });
  },
});
```

## Per-Call Header Injection

Agents can inject headers when calling other tools. This enables use cases
like audit correlation where an orchestrating agent stamps metadata on
downstream calls.

```typescript
import { getCurrentPropagatedHeaders, McpMeshTool } from "@mcpmesh/sdk";

agent.addTool({
  name: "relay",
  capability: "relay_headers",
  dependencies: ["echo_headers"],
  parameters: z.object({}),
  execute: async ({}, { echo_headers }: { echo_headers: McpMeshTool | null }) => {
    // Check what's already propagated
    const propagated = getCurrentPropagatedHeaders();

    if (!propagated["x-audit-id"]) {
      // Inject a new header on this specific call
      const result = await echo_headers!({}, {
        headers: { "x-audit-id": "audit-12345" },
      });
      return JSON.stringify(result);
    }

    const result = await echo_headers!({});
    return JSON.stringify(result);
  },
});
```

**API:** `await tool(args, { headers: { "header-name": "value" } })`

The `headers` option is passed as part of the second argument (options object):

```typescript
// No tool arguments, just headers
const result = await tool({}, { headers: { "x-audit-id": "abc" } });

// With tool arguments
const result = await tool(
  { query: "test" },
  { headers: { "x-audit-id": "abc" } }
);

// Via callTool
const result = await tool.callTool("specific_tool", { query: "test" }, {
  headers: { "x-audit-id": "abc" },
});
```

### Merge Semantics

Per-call headers merge on top of session-level propagated headers:

```
Session propagated headers (from incoming request)
  + Per-call headers (from options.headers)
  = Merged headers sent downstream
```

Per-call headers **win** on conflict. All headers (session and per-call)
are filtered by the `MCP_MESH_PROPAGATE_HEADERS` prefix allowlist — agents
cannot inject arbitrary headers unless the operator explicitly allows them.

## Example: Auth Token Forwarding

Forward bearer tokens through the mesh so each agent can enforce its own
authorization:

```bash
# Set on all agents in the chain:
export MCP_MESH_PROPAGATE_HEADERS=authorization

# API gateway or client sends a token:
curl -H "Authorization: Bearer tok_abc123" \
  http://localhost:8080/api/process
```

The `Authorization` header flows automatically through every agent call.

## Cross-Language Behavior

All three SDKs inject headers via two mechanisms simultaneously:

1. **HTTP headers** on outgoing requests — works for Python and Java receivers
2. **`_mesh_headers` argument** tunneled in JSON-RPC args — works for
   TypeScript receivers (where FastMCP doesn't expose HTTP headers)

The `_mesh_headers` argument is stripped before user code sees it. This
dual mechanism is transparent — headers flow correctly regardless of which
SDK combination is in the chain.

**TypeScript limitation:** TypeScript agents cannot capture headers from
direct external HTTP callers (curl, API gateways) due to FastMCP not
exposing HTTP headers. Headers are only received from other mesh agents
that tunnel them via `_mesh_headers`. Agent-to-agent calls work correctly
across all SDK combinations.

## Environment Variables

| Variable                     | Description                                       | Default  |
| ---------------------------- | ------------------------------------------------- | -------- |
| `MCP_MESH_PROPAGATE_HEADERS` | Comma-separated header name prefixes to forward   | _(none)_ |

## See Also

- `meshctl man observability` — Distributed tracing with X-Trace-ID
- `meshctl man environment` — All configuration variables
- `meshctl man proxies --typescript` — Inter-agent communication mechanics
- `meshctl man api --typescript` — Adding mesh to existing web frameworks
