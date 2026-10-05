# Environment Variables

> Configure MCP Mesh via environment variables

## Overview

MCP Mesh can be configured using environment variables. For agents they override decorator, `mesh()` and `@MeshAgent` parameters, which lets the same code run locally (using code defaults) and in Kubernetes (using Helm-injected env vars) without modification.

Every variable below is listed with the components that read it:

- **Py**, **TS**, **Java** - the agent runtimes (Python, TypeScript, Java). "All SDKs" means all three.
- **registry** - the `mcp-mesh-registry` binary.
- **meshui** - the dashboard server.
- **meshctl** - the CLI itself (not the processes it starts).

A variable not listed for a component has no effect on it.

## Configuration Hierarchy

For an agent, the environment it starts with wins over the decorator / `mesh()` / annotation parameters in its code.

When `meshctl start` launches an agent, the agent's environment is built in this order (highest wins):

1. `--env KEY=VALUE` flags
2. `--env-file` entries
3. Variables exported in the shell that runs meshctl

`MCP_MESH_REGISTRY_URL`, `MCP_MESH_LOG_LEVEL` and `MCP_MESH_DEBUG_MODE` are then set by meshctl from its own configuration, so for those three only an `--env` flag overrides meshctl.

meshctl reads its own settings (the `meshctl` table below) from the shell environment when it starts, before it applies `--env-file` or `--env`. Those flags change what the agents see, not meshctl itself.

## Empty Values Mean Unset

In all three SDKs an empty or whitespace-only value is treated as if the variable were not set, so the default applies. An unset Helm key that renders `NAME: ""` therefore behaves like an absent variable. The one exception is `MCP_MESH_ENABLED`, which fails closed: an empty value disables the runtime (see below).

## A note on env var prefixing

mcp-mesh's own env vars use the `MCP_MESH_*` prefix. Several env vars in this reference appear WITHOUT the prefix:

- **Vendor SDK conventions** - `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `VAULT_TOKEN`, `AWS_*` are consumed directly by the underlying SDKs. Renaming would break those wrappers.
- **Registry-server boot vars** - `HOST`, `PORT`, `DATABASE_URL`, `DB_*` configure the registry binary's listener and storage.
- **Observability stack** - `REDIS_URL`, `TEMPO_URL`, `TELEMETRY_*`, `TRACE_*` follow OpenTelemetry / observability-tooling conventions.

## Agent Configuration

### Identity and Networking

| Variable                   | Read by         | Default         | Purpose |
| -------------------------- | --------------- | --------------- | ------- |
| `MCP_MESH_AGENT_NAME`      | All SDKs        | code value      | Agent name |
| `MCP_MESH_AGENT_ID`        | Py              | `<name>-<8 hex>` | Pin the full agent id instead of generating one |
| `MCP_MESH_NAMESPACE`       | All SDKs        | `default`       | Namespace for isolation |
| `MCP_MESH_REGISTRY_URL`    | All SDKs, meshui, meshctl | `http://localhost:8000` | Registry URL |
| `MCP_MESH_HTTP_PORT`       | All SDKs        | code value      | Port the agent serves on |
| `MCP_MESH_HTTP_HOST`       | All SDKs        | auto-detected   | Hostname announced to the registry |
| `HOST`                     | Py, TS, registry | `0.0.0.0` (agents) | Bind address |
| `MCP_MESH_HEALTH_INTERVAL` | All SDKs        | `5`             | Heartbeat cadence to the registry (seconds) |
| `MCP_MESH_HEALTH_CHECK_TTL` | All SDKs       | `15`            | How often the agent's health check re-runs (seconds) |

```bash
export MCP_MESH_AGENT_NAME=my-service
export MCP_MESH_NAMESPACE=production
export MCP_MESH_REGISTRY_URL=http://localhost:8000
export MCP_MESH_HTTP_PORT=8080
export MCP_MESH_HTTP_HOST=my-service
```

`MCP_MESH_HTTP_HOST` decides whether replicas share traffic: the registry hands back one winner's announced host, so announcing a Kubernetes Service name spreads calls across its pods, while an auto-detected pod IP pins every call to one process. The `mcp-mesh-agent` Helm chart announces the Service DNS name for you; override it with `agent.advertisedHost`. How the registry picks the winner is the tiebreaker in `meshctl man audit`. TypeScript gateways built with `meshExpress` read the same identity variables as `mesh()` agents.

### Python Runtime

| Variable                          | Default | Purpose |
| --------------------------------- | ------- | ------- |
| `MCP_MESH_ENABLED`                | enabled | The off switch (see below) |
| `MCP_MESH_AUTO_RUN`               | `true`  | Start the HTTP server and keep the process alive |
| `MCP_MESH_HTTP_ENABLED`           | `true`  | Set `false` to skip the agent's HTTP server setup |
| `MCP_MESH_API_NAME`               | -       | Name for a `@mesh.route` gateway (falls back to `MCP_MESH_AGENT_NAME`) |
| `MCP_MESH_A2A_NAME`               | -       | Name for a `@mesh.a2a` gateway (falls back to `MCP_MESH_AGENT_NAME`) |
| `MCP_MESH_STANDALONE`             | `false` | Run a `@mesh.route` / `@mesh.a2a` gateway without contacting the registry |
| `MCP_MESH_DEBOUNCE_DELAY`         | `1.0`   | Seconds to wait after the last decorator before starting the runtime |
| `MCP_MESH_SERVER_STARTUP_TIMEOUT` | `30`    | Seconds to wait for the HTTP server to prove it is serving before the first registration |
| `MCP_MESH_SESSION_TTL`            | `3600`  | Lifetime of a session-affinity assignment (seconds) |

### MCP_MESH_ENABLED - the off switch

`MCP_MESH_ENABLED=false` makes the Python runtime inert: no startup pipeline, no registration, no heartbeat, no dependency injection. Decorators still import and still record their metadata, so your module loads normally - mesh simply never runs. This is the flag to use in unit tests and in any process that imports an agent module without wanting to join a mesh.

It fails **closed**. Unset means enabled; `true`, `1`, `yes` and `on` enable it; anything else - including `false`, `0`, `off`, an empty value and a typo - disables it and logs why. An empty value is a routine outcome of an unset Helm key, and for the one flag whose job is to turn mesh off, "I could not parse this" must not mean "on".

Do not use `MCP_MESH_AUTO_RUN=false` for this. It gates the HTTP server and the process lifetime only: an agent with auto-run disabled still registers and still heartbeats, by design. See `meshctl man decorators` for the full split.

### Logging

| Variable              | Read by                          | Default | Purpose |
| --------------------- | -------------------------------- | ------- | ------- |
| `MCP_MESH_LOG_LEVEL`  | Py, TS, registry, meshui, meshctl | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `MCP_MESH_DEBUG_MODE` | Py, TS, registry, meshctl         | `false` | Force `DEBUG` level |

Java agents log through Spring Boot: set `logging.level.io.mcpmesh` instead.

### Tool Dispatch

| Variable                  | Read by | Default | Purpose |
| ------------------------- | ------- | ------- | ------- |
| `MCP_MESH_TOOL_WORKERS`   | Py, TS  | Py `1`; TS `min(8, max(2, cpus))` | Worker loops (Python) / worker threads (TypeScript) for tool bodies |
| `MCP_MESH_TOOL_ISOLATION` | Py, TS  | `true`  | Run tool bodies off the main event loop |

```bash
# Python: N=1 (default) runs lifespan startup, every tool body and lifespan
# exit on one user loop, so loop-bound resources created in lifespan
# (asyncpg.Pool, redis.asyncio, aiohttp.ClientSession) work in every tool.
# /health, /ready, /livez stay responsive on a separate framework loop.
# N>1 is for tool bodies doing sync blocking work; resources created in
# lifespan bind to worker-0 only. Prefer asyncio.to_thread(blocking_call).
#
# TypeScript: the size of the worker_threads pool that isolated tool
# bodies run on.
export MCP_MESH_TOOL_WORKERS=1

# Default true. Runs each async tool body off the main event loop - Python
# dispatches it to the mesh worker loop, TypeScript runs it on a worker
# thread - so a blocking or long-running tool call cannot stall the main
# loop that serves /health, /ready, the HTTP transport and the heartbeat.
# Set to false to run tool bodies inline on the main loop.
#
# - Python: only async tools are wrapped (sync tools already run off-loop
#   via FastMCP); streaming tools always run inline.
# - TypeScript: a .ts/.mts/.cts/.tsx entrypoint is loaded in the worker
#   through `tsx`, which must be in your dependencies. A2A-consumer tools,
#   MeshJob/task tools and service-view tools always run inline.
export MCP_MESH_TOOL_ISOLATION=true
```

### Strict DI Diagnostics (all SDKs)

```bash
# Default: false. When truthy, ambiguous or skipped dependency-injection
# configurations fail at decoration/startup instead of warning. Injection
# semantics are unchanged - only the diagnostic severity is promoted.
#
# - Python: raises StrictDIError at decoration/startup.
# - TypeScript: an addTool whose dependencies outnumber the execute
#   parameters after args throws StrictDIError at registration.
# - Java: promotes the boot-time dependency/parameter arity mismatch and
#   the @MeshRoute / @MeshA2A legacy-order warning to a startup failure.
#   A contradicting @MeshInject value is fatal either way.
# All three accept true / 1 / yes / on (any case).
export MCP_MESH_STRICT_DI=true
```

### Dependency Settling Window (all SDKs)

```bash
# Float seconds, default: 20. 0 disables the grace entirely.
#
# During agent startup, declared dependencies resolve asynchronously (first
# full heartbeat cycle). A call that arrives while a declared dependency is
# still unresolved waits - bounded by the remaining window - for that
# dependency's resolution event before proceeding. Event-driven: resolution
# at 800ms unblocks at 800ms; the value is a ceiling, never a sleep.
# The window starts when the agent's first dependency is declared.
#
# Once the agent settles (all declared dependencies resolved at least once,
# OR the window expires), calls never wait again and unresolved
# dependencies inject None/null exactly as before.
#
# Scope: dependency-injection call paths (tools and routes), A2A producer
# handlers and the LLM provider slot, on all three runtimes. Not covered:
# dependencies used from startup hooks / lifespan, dependencies captured at
# module scope, and the tool list an LLM consumer's filter assembles (only
# its provider slot waits).
#
# Tuning: lower it (e.g. 2-5) in integration tests that intentionally
# exercise unresolved-dependency behavior, so degraded-path assertions
# don't sit out the full default window.
export MCP_MESH_SETTLE_TIMEOUT=20
```

### Schema Verdict Policy (issue #547)

| Variable                            | Read by  | Default  | Purpose |
| ----------------------------------- | -------- | -------- | ------- |
| `MCP_MESH_SCHEMA_STRICT`            | All SDKs | `false`  | Treat schema-normalizer WARN verdicts as BLOCK and refuse to start |
| `MCP_MESH_SCHEMA_MAX_INLINED_NODES` | All SDKs | `500000` | Ceiling on JSON nodes materialized while inlining `$defs`; exceeding it is a BLOCK |

```bash
# Production hardening knob; per-tool output_schema_strict=false (Python) /
# outputSchemaStrict: false (TS) / outputSchemaStrict = false (Java)
# overrides it for that one tool.
export MCP_MESH_SCHEMA_STRICT=true

# Raise it if a legitimately large model is refused - a consumer-side
# expected_type BLOCK has NO per-tool override, so this is the only remedy.
export MCP_MESH_SCHEMA_MAX_INLINED_NODES=2000000
```

See `meshctl man schema-matching` for the verdict tiers and per-tool overrides.

## Calls and Timeouts

| Variable                     | Read by  | Default | Purpose |
| ---------------------------- | -------- | ------- | ------- |
| `MCP_MESH_CALL_TIMEOUT`      | All SDKs | `300`   | Budget for an outgoing mesh call (seconds) |
| `MCP_MESH_PROXY_TIMEOUT`     | registry | `60`    | Registry proxy timeout when no `X-Mesh-Timeout` header is sent (capped at 600) |
| `MCP_MESH_SSE_DRAIN_TIMEOUT` | TS       | `300`   | Seconds `mesh.sseStream` waits for a backpressured consumer (`0` = forever) |
| `MESH_PROVIDER_TIMEOUT_MS`   | TS       | `300000` | Timeout for a `mesh.llm` call to its LLM provider (milliseconds) |
| `MESH_TOOL_TIMEOUT_MS`       | TS       | `30000` | Timeout for each tool call the LLM makes from a `mesh.llm` loop (milliseconds) |
| `MCP_MESH_PROPAGATE_HEADERS` | All SDKs, registry | - | Header allowlist to capture and relay (see `meshctl man headers`) |

```bash
export MCP_MESH_CALL_TIMEOUT=300
export MCP_MESH_PROXY_TIMEOUT=60
export MCP_MESH_PROPAGATE_HEADERS=authorization,x-request-id,x-tenant-*
```

In every runtime the winning value drives BOTH the advertised `X-Mesh-Timeout` and the local HTTP client timeout, so an agent never promises a provider a budget it will not itself wait out. An inbound `X-Mesh-Timeout` overrides the local value.

Only TypeScript has a per-dependency override (`timeout`, or `streamTimeout` when `streaming` is set, in `dependencyKwargs`). Python and Java resolve the budget from `MCP_MESH_CALL_TIMEOUT`, else 300s.

Streamed responses (e.g., SSE) routed through the registry proxy are bounded by the same call timeout - the proxy ends the exchange when it elapses, even mid-stream. Send a larger `X-Mesh-Timeout` header (or raise `MCP_MESH_PROXY_TIMEOUT`) for long-lived streams; the registry proxy caps both at 600 seconds.

On the browser-facing side, `mesh.sseStream` (TypeScript) treats a slow consumer as slow, not gone: it waits for the response to drain before sending the next frame. A consumer that stalls without ever disconnecting is abandoned after `MCP_MESH_SSE_DRAIN_TIMEOUT`, which releases the upstream stream it was holding open.

In `MCP_MESH_PROPAGATE_HEADERS` a plain entry is an exact header name and an entry ending in `*` is a prefix.

## LLM Provider Configuration

Required for LLM provider agents:

| Variable                       | Read by | Purpose |
| ------------------------------ | ------- | ------- |
| `ANTHROPIC_API_KEY`            | Py, TS  | Anthropic Claude |
| `OPENAI_API_KEY`               | Py, TS  | OpenAI |
| `GOOGLE_API_KEY`               | Py, TS  | Gemini via AI Studio |
| `GOOGLE_GENERATIVE_AI_API_KEY` | TS      | Gemini via AI Studio (the Vercel AI SDK's own name; either works) |

Java reads provider keys through Spring AI properties: `spring.ai.anthropic.api-key`, `spring.ai.openai.api-key` and `spring.ai.google.genai.api-key`. Map them to the variables above in `application.yml` (for example `api-key: ${ANTHROPIC_API_KEY}`), or set the relaxed-binding names such as `SPRING_AI_ANTHROPIC_API_KEY` directly.

### Vertex AI (Gemini via IAM)

Use the `vertex_ai/` model prefix (Python/TS) or `provider = "vertex_ai"` (Java) to call Gemini through Google Cloud's Vertex AI instead of AI Studio. Credentials come from Google Application Default Credentials in every runtime: `gcloud auth application-default login`, `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`, or Workload Identity.

| Runtime    | Project                                   | Location |
| ---------- | ----------------------------------------- | -------- |
| Python     | `GOOGLE_CLOUD_PROJECT` (else the ADC quota project) | `GOOGLE_CLOUD_LOCATION` (default `us-central1`) |
| TypeScript | `GOOGLE_CLOUD_PROJECT` or `GOOGLE_VERTEX_PROJECT` (required) | `GOOGLE_CLOUD_LOCATION` or `GOOGLE_VERTEX_LOCATION` (required) |
| Java       | `spring.ai.google.genai.project-id` (env `SPRING_AI_GOOGLE_GENAI_PROJECT_ID`) | `spring.ai.google.genai.location` (env `SPRING_AI_GOOGLE_GENAI_LOCATION`) |

```python
@mesh.llm_provider(
    capability="llm",
    tags=["gemini", "vertex"],
    model="vertex_ai/gemini-2.5-flash",  # vs "gemini/gemini-2.5-flash" for AI Studio
)
def my_provider(): pass
```

The Python runtime calls Vertex through the bundled `google-genai` SDK; no extra install is needed. TypeScript bundles `@ai-sdk/google-vertex`, which fails with a `LoadSettingError` on the first call if the project or location is unset. In Java, setting the project id and location (and no API key) selects the Vertex backend of the `spring-ai-starter-model-google-genai` model; when both an API key and a project are set, `spring.ai.google.genai.vertex-ai=true` forces Vertex.

### Python Provider Tuning

| Variable                                  | Default | Purpose |
| ----------------------------------------- | ------- | ------- |
| `MCP_MESH_NATIVE_LLM`                     | on      | Set `0` to route provider calls through LiteLLM instead of the native vendor SDKs (needs `pip install 'mcp-mesh[litellm]'`) |
| `MCP_MESH_HINT_FALLBACK_TIMEOUT`          | `90`    | Seconds for the bounded structured-output retry after a HINT-mode answer fails to parse |
| `MCP_MESH_CLAUDE_FORCE_RESPONSE_FORMAT`   | `false` | LiteLLM path only: ask Claude for `response_format` first instead of HINT mode |
| `MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS` | on      | Set `0` to turn off server-enforced structured output with tools on Gemini 3 |
| `MCP_MESH_LLM_SYNTHETIC_RETRY_MAX`        | `1`     | Corrective retries when Claude returns malformed structured output (`0` disables) |

## LLM Agent Configuration

| Variable                  | Read by  | Purpose |
| ------------------------- | -------- | ------- |
| `MESH_LLM_MODEL`          | Py, TS   | Model override a consumer forwards to its provider |
| `MESH_LLM_MAX_ITERATIONS` | All SDKs | Max agentic loop iterations (default 10) |
| `MESH_LLM_FILTER_MODE`    | All SDKs | Tool filter mode: `all`, `best_match`, `*` |

```bash
export MESH_LLM_MODEL=gpt-4o
export MESH_LLM_MAX_ITERATIONS=5
export MESH_LLM_FILTER_MODE=all
```

Java has no `MESH_LLM_MODEL`: set the model on `@MeshLlm` or its fluent builder. Provider selection itself is governed by the provider selector and resolved through mesh DI - there is no environment override for it. To switch backends per environment, deploy a different LLM provider agent and let the selector resolve the right one.

**Use case**: Same agent code, different pinned model per environment:

```bash
# Development - cheaper/faster model
meshctl start agent.py --env MESH_LLM_MODEL=gpt-4o-mini

# Production - stronger model
meshctl start agent.py --env MESH_LLM_MODEL=claude-sonnet-4-5
```

## Observability

| Variable                                   | Read by | Default | Purpose |
| ------------------------------------------ | ------- | ------- | ------- |
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED`     | All SDKs, registry, meshui | `false` (`true` for meshui) | Publish and collect trace spans |
| `REDIS_URL`                                | All SDKs, registry, meshui | `redis://localhost:6379` | Redis for the `mesh:trace` stream (and Python session affinity) |
| `MCP_MESH_TRACE_STREAM_MAXLEN`             | All SDKs | `100000` | Producer-side `XADD MAXLEN ~` ceiling on `mesh:trace` (`0` = no cap) |
| `MCP_MESH_TELEMETRY_ENABLED`               | Py | `true` | Set `false` to stop the Python proxy publishing spans for its outgoing calls |
| `TEMPO_URL`                                | registry, meshui | `http://localhost:3200` | Tempo query API |
| `TELEMETRY_ENDPOINT`                       | registry | `localhost:4317` | OTLP endpoint the registry exports to |
| `TELEMETRY_PROTOCOL`                       | registry | `grpc` | `grpc` or `http` |
| `TRACE_EXPORTER_TYPE`                      | registry | `otlp` | `otlp`, `console`, `json` |
| `OTLP_ENDPOINT`                            | registry | - | Alternative name for `TELEMETRY_ENDPOINT`, used when that is unset |
| `TRACE_BATCH_SIZE`                         | registry | `100` | Stream entries the registry reads per batch |
| `TRACE_TIMEOUT`                            | registry | `5m` | `console` / `json` exporters: how long an incomplete trace is held before it is emitted (Go duration) |
| `TRACE_PRETTY_OUTPUT`                      | registry | `true` | `console` exporter: pretty-printed output (`false` for compact) |
| `TRACE_JSON_OUTPUT_DIR`                    | registry | - | `json` exporter: directory the trace files are written to |
| `TRACE_ENABLE_STATS`                       | registry | `true` | `console` / `json` exporters: also keep trace-processing statistics (`false` turns them off) |
| `MCP_MESH_TRACE_RETENTION`                 | registry, meshui | `24h` | Trim `mesh:trace` entries older than this (`0` = no trimming) |
| `MCP_MESH_TRACE_CONSUMER_GROUP`            | registry | `mcp-mesh-registry-processors` | Redis consumer group the registry reads with |
| `MCP_MESH_UI_TRACE_CONSUMER_GROUP`         | meshui | `mcp-mesh-ui-dashboard` | Redis consumer group meshui reads with |
| `MCP_MESH_TELEMETRY_AGGREGATE_RETENTION`   | meshui | `24h` | Age-out window for dashboard aggregates (`0` = no age pruning) |
| `MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES` | meshui | `10000` | Key ceiling per aggregate map (`0` = no ceiling) |
| `MCP_MESH_UI_PORT`                         | meshui, meshctl | `3080` | Dashboard port |
| `MCP_MESH_UI_BASE_PATH`                    | meshui | - | Base path for path-based ingress routing |

```bash
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
export REDIS_URL=redis://localhost:6379
export TEMPO_URL=http://localhost:3200
export TELEMETRY_ENDPOINT=localhost:4317
```

A second meshui or registry pointed at a live mesh needs its own consumer group: Redis gives each stream entry to one consumer per group, so a second reader on the default group takes entries away from the running one. An edge aggregate key costs ~2.1 KB, so the default `MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES` admits ~20 MB of edge aggregates. See `meshctl man observability` for which store `meshctl trace` reads.

## Media Storage

| Variable                          | Read by  | Default               | Purpose |
| --------------------------------- | -------- | --------------------- | ------- |
| `MCP_MESH_MEDIA_STORAGE`          | All SDKs | `local`               | Backend: `local` or `s3` |
| `MCP_MESH_MEDIA_STORAGE_PATH`     | All SDKs | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `MCP_MESH_MEDIA_STORAGE_BUCKET`   | All SDKs | -                     | S3 bucket name |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | All SDKs | -                     | S3-compatible endpoint URL (omit for AWS) |
| `MCP_MESH_MEDIA_STORAGE_PREFIX`   | All SDKs | `media/`              | Key/directory prefix |
| `MCP_MESH_MEDIA_STORAGE_VALIDATE` | Py       | `false`               | Probe the S3 bucket at startup instead of at first use |
| `AWS_ACCESS_KEY_ID`               | S3 SDK   | -                     | S3 access key (or use IAM roles) |
| `AWS_SECRET_ACCESS_KEY`           | S3 SDK   | -                     | S3 secret key (or use IAM roles) |

```bash
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000  # omit for AWS
```

In distributed deployments (Docker, Kubernetes), all agents that read or write media must share the same storage config. Use S3 for multi-container setups - `file://` URIs don't work across pods. See `meshctl man media`.

## Security & TLS

### Agent TLS

| Variable                  | Read by  | Default | Purpose |
| ------------------------- | -------- | ------- | ------- |
| `MCP_MESH_TLS_MODE`       | All SDKs, registry | `off` | `off`, `auto`, `strict` |
| `MCP_MESH_TLS_CERT`       | All SDKs, registry | - | Certificate PEM path |
| `MCP_MESH_TLS_KEY`        | All SDKs, registry | - | Private key PEM path |
| `MCP_MESH_TLS_CA`         | All SDKs, registry | - | CA certificate PEM path |
| `MCP_MESH_TLS_PROVIDER`   | All SDKs | `file` | `file`, `vault`, `spire` (`spire`: Python and TypeScript only) |
| `MCP_MESH_TRUST_DOMAIN`   | All SDKs | `mcp-mesh.local` | Trust domain for Vault CNs and SPIRE |
| `MCP_MESH_VAULT_ADDR`     | All SDKs | - | Vault server URL |
| `MCP_MESH_VAULT_PKI_PATH` | All SDKs | - | Vault PKI issue path |
| `VAULT_TOKEN`             | All SDKs | - | Vault token |
| `MCP_MESH_VAULT_TTL`      | All SDKs | `24h` | Certificate TTL |
| `MCP_MESH_SPIRE_SOCKET`   | Py, TS, registry | `/run/spire/agent/sockets/agent.sock` | SPIRE Workload API socket |

The Java runtime refuses to start with `MCP_MESH_TLS_PROVIDER=spire` when `MCP_MESH_TLS_MODE` is `auto` or `strict`; with TLS `off` it ignores the provider. See `meshctl man security`.

### Per-Service TLS

Each of these prefixes reads `<PREFIX>_CA`, `<PREFIX>_CERT`, `<PREFIX>_KEY` and `<PREFIX>_SKIP_VERIFY`:

| Prefix                  | Read by          | Connection |
| ----------------------- | ---------------- | ---------- |
| `MCP_MESH_REGISTRY_TLS` | meshui           | meshui to the registry |
| `REDIS_TLS`             | registry, meshui | Redis |
| `TEMPO_TLS`             | registry, meshui | Tempo query API |
| `TELEMETRY_TLS`         | registry         | OTLP exporter |
| `MCP_MESH_TLS`          | meshctl          | meshctl to the registry |

### Registry Trust

| Variable                      | Read by  | Purpose |
| ----------------------------- | -------- | ------- |
| `MCP_MESH_TRUST_BACKEND`      | registry | `localca`, `filestore`, `k8s-secrets`, `spire` (comma-separated chain) |
| `MCP_MESH_TRUST_DIR`          | registry, meshctl | Directory for `filestore` / `localca` |
| `MCP_MESH_K8S_NAMESPACE`      | registry | Namespace for `k8s-secrets` |
| `MCP_MESH_K8S_LABEL_SELECTOR` | registry | Label selector for `k8s-secrets` |
| `MCP_MESH_ADMIN_PORT`         | registry | Serve `/admin/*` only on this port |
| `MCP_MESH_ADMIN_TLS`          | registry | Admin port uses the main port's TLS certificate and client-certificate policy, when registry TLS is configured (default `false`) |

The admin port is plain HTTP and unauthenticated unless `MCP_MESH_ADMIN_TLS=true` and the registry itself has TLS configured; with `MCP_MESH_ADMIN_TLS=true` but no registry TLS it stays plain HTTP. With admin TLS on, `MCP_MESH_TLS_MODE=auto` still admits callers without a client certificate (so anyone who reaches the port can, for example, drain the registry), and only `strict` requires a trusted one. Restrict the port at the network layer in every mode. The registry's only enforcement is client-certificate verification under `MCP_MESH_TLS_MODE`; there is no token alternative.

## MeshJob event channel

```bash
# All SDKs. Max JobProxy instances held in the SDK's process-wide LRU cache
# (default: 256). Used by the post_event / subscribe_events helpers in every
# runtime. Invalid / non-positive values fall back to the default.
export MCP_MESH_JOBPROXY_CACHE_MAX=256

# Registry. How long CancelJob waits (ms) after writing the synthetic
# "cancelled" event before forwarding the cancel to the owner replica
# (default: 200, capped at 10000). 0 disables the grace.
export MCP_MESH_CANCEL_EVENT_GRACE_MS=200
```

## Registry Configuration

All read by the registry:

```bash
# Server binding
export HOST=0.0.0.0
export PORT=8000

# Database (meshui reads DATABASE_URL too)
export DATABASE_URL=mcp_mesh_registry.db  # SQLite
export DATABASE_URL=postgresql://user:pass@host:5432/db  # PostgreSQL

# Health monitoring
export DEFAULT_TIMEOUT_THRESHOLD=20   # Mark unhealthy after this many seconds without a heartbeat
export HEALTH_CHECK_INTERVAL=10       # Scan frequency (seconds)

# Sweep retention - how long unhealthy/unknown agents and orphan
# schema_entries are kept before the periodic sweep purges them. Go
# duration string. Default: 1h. "0" disables the agent/schema sweep.
export MCP_MESH_RETENTION=1h

# registry_events row cap - a table-size safety limit, enforced
# independently of MCP_MESH_RETENTION. Default: 100000. "0" disables it.
export MCP_MESH_EVENT_MAX_ROWS=100000

# How often the periodic job/agent sweep runs. Go duration. Default: 5m.
export MCP_MESH_SWEEP_INTERVAL=5m

# MeshJob default total-runtime ceiling for jobs that set no
# total_deadline, measured from submission. The effective ceiling is
# max(MCP_MESH_JOB_STALE_TIMEOUT, max_duration). Default: off. NOT the
# lease window, which is derived per job from max_duration.
export MCP_MESH_JOB_STALE_TIMEOUT=2h

# Maximum request body, in bytes, on the main and admin listeners. An
# over-limit request is refused with 413. Default: 10485760 (10MB).
# 0 disables the limit.
export MCP_MESH_MAX_REQUEST_BODY_BYTES=10485760

# Public URL prefix stamped onto A2A surfaces (public_url, agent card URL)
export MCP_MESH_PUBLIC_URL_PREFIX=https://agents.example.com

# SQLite / connection-pool tuning (integers)
export DB_BUSY_TIMEOUT=5000           # milliseconds
export DB_JOURNAL_MODE=WAL
export DB_SYNCHRONOUS=NORMAL
export DB_CACHE_SIZE=10000
export DB_MAX_OPEN_CONNECTIONS=25
export DB_MAX_IDLE_CONNECTIONS=5
export DB_CONN_MAX_LIFETIME=300       # seconds
```

## meshctl

| Variable                     | Default | Purpose |
| ---------------------------- | ------- | ------- |
| `MCP_MESH_REGISTRY_HOST`     | `localhost` | Host meshctl starts or reaches the registry on when no `--registry-*` flag is given |
| `MCP_MESH_REGISTRY_PORT`     | `8000`  | Port meshctl starts or reaches the registry on |
| `MCP_MESH_DB_PATH`           | `mcp_mesh_registry.db` | SQLite file for a registry meshctl starts |
| `MCP_MESH_STARTUP_TIMEOUT`   | `30`    | Seconds to wait for a started registry or agent (integer) |
| `MCP_MESH_SHUTDOWN_TIMEOUT`  | `30`    | Seconds to wait for a graceful stop (integer) |
| `MCP_MESH_RELOAD_DEBOUNCE`   | `0.5`   | `--watch`: seconds of quiet before a restart |
| `MCP_MESH_RELOAD_PORT_DELAY` | `0.5`   | `--watch`: seconds to wait for the port after stopping |
| `MCP_MESH_RELOAD_PRECHECK`   | `true`  | `--watch`: syntax-check before restarting |
| `MESHCTL_TEMPLATE_DIR`       | embedded | Scaffold template directory |

Agents do not read `MCP_MESH_REGISTRY_HOST` or `MCP_MESH_REGISTRY_PORT`; they read `MCP_MESH_REGISTRY_URL`.

## Java Runtime

| Variable               | Purpose |
| ---------------------- | ------- |
| `MESH_NATIVE_LIB_PATH` | Load the native core library from this path instead of the bundled one |

## Kubernetes Downward API

| Variable        | Read by  | Purpose |
| --------------- | -------- | ------- |
| `POD_IP`        | Py, Java | Python: the address other replicas forward a pinned session's calls to (default `localhost`, so set it in multi-replica deployments); both: recorded on trace spans |
| `POD_NAMESPACE` | Java     | Recorded on trace spans |

## Environment Profiles

### Development

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_HEALTH_INTERVAL=5
```

### Production

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_REGISTRY_URL=https://registry.company.com
MCP_MESH_NAMESPACE=production

# TLS (choose one provider)
MCP_MESH_TLS_MODE=strict
MCP_MESH_TLS_PROVIDER=vault
MCP_MESH_VAULT_ADDR=https://vault.company.com:8200
MCP_MESH_VAULT_PKI_PATH=pki_int/issue/mesh-agent
```

### Testing

```bash
# .env.testing (Python)
MCP_MESH_LOG_LEVEL=WARNING
MCP_MESH_ENABLED=false          # Inert: no pipeline, no registration, no heartbeat
```

## Using Environment Files

```bash
meshctl start my_agent.py --env-file .env.development

# Individual variables
meshctl start my_agent.py --env MCP_MESH_LOG_LEVEL=DEBUG
```

## Docker Configuration

```yaml
# docker-compose.yml
services:
  my-agent:
    environment:
      - HOST=0.0.0.0
      - MCP_MESH_HTTP_HOST=my-agent
      - MCP_MESH_HTTP_PORT=8080
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_LOG_LEVEL=INFO
      - MCP_MESH_NAMESPACE=docker
```

## Kubernetes Configuration

```yaml
# deployment.yaml
env:
  - name: MCP_MESH_REGISTRY_URL
    value: "https://registry.mcp-mesh:8000"
  - name: MCP_MESH_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # TLS (Vault provider example)
  - name: MCP_MESH_TLS_MODE
    value: "strict"
  - name: MCP_MESH_TLS_PROVIDER
    value: "vault"
  - name: MCP_MESH_VAULT_ADDR
    value: "https://vault.vault-system:8200"
  - name: MCP_MESH_VAULT_PKI_PATH
    value: "pki_int/issue/mesh-agent"
  - name: VAULT_TOKEN
    valueFrom:
      secretKeyRef:
        name: vault-agent-token
        key: token
```

## Common Issues

### Port Already in Use

```bash
lsof -i :8080
export MCP_MESH_HTTP_PORT=8081
```

### Registry Connection Failed

```bash
curl -s http://localhost:8000/health
export MCP_MESH_REGISTRY_URL=http://backup-registry:8000
```

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man registry` - Registry configuration
- `meshctl man health` - Health monitoring settings
- `meshctl man security` - TLS, trust backends and the admin port
- `meshctl man headers` - Header propagation
