# Environment Variables Reference

> Configure MCP Mesh agents and services with environment variables

## Overview

MCP Mesh can be configured using environment variables, allowing you to customize behavior without changing code. Environment variables override `@mesh.agent` decorator parameters and provide flexibility for different deployment environments.

## Essential Environment Variables

### Logging and Debug

```bash
# Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export MCP_MESH_LOG_LEVEL=DEBUG

# Enable debug mode (forces DEBUG level)
export MCP_MESH_DEBUG_MODE=true
```

### Registry Configuration

```bash
# Complete registry URL
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Or set host and port separately
export MCP_MESH_REGISTRY_HOST=localhost
export MCP_MESH_REGISTRY_PORT=8000
```

### Agent Configuration

```bash
# Override agent name
export MCP_MESH_AGENT_NAME=my-custom-agent

# Set agent namespace
export MCP_MESH_NAMESPACE=development

# Enable/disable auto-run
export MCP_MESH_AUTO_RUN=true

# Auto-run heartbeat interval (seconds)
export MCP_MESH_AUTO_RUN_INTERVAL=30
```

### Agent Identity & Version

```bash
# Agent semantic version (default: "1.0.0")
# Typically set in source code via @mesh.agent decorator, not env var
export MCP_MESH_AGENT_VERSION=1.2.0

# Runtime-assigned agent ID (set by registry, read-only)
# MCP_MESH_AGENT_ID — assigned at registration

# Override agent capabilities
export MCP_MESH_AGENT_CAPABILITIES=greeting,translation

# Heartbeat interval in seconds (Java runtime, default: 5)
export MCP_MESH_HEARTBEAT_INTERVAL=5

# Session time-to-live in seconds (default: 3600)
export MCP_MESH_SESSION_TTL=3600
```

### HTTP Server Settings

```bash
# External hostname announced to registry (also used as bind hint)
# In K8s/production, set to the externally reachable hostname (e.g., service name).
# Agents bind to 0.0.0.0 internally regardless.
export MCP_MESH_HTTP_HOST=0.0.0.0

# Agent HTTP port
export MCP_MESH_HTTP_PORT=8080

# Enable/disable HTTP transport
export MCP_MESH_HTTP_ENABLED=true
```

### Health and Monitoring

```bash
# Health check interval (seconds)
export MCP_MESH_HEALTH_INTERVAL=30

# Enable global mesh functionality
export MCP_MESH_ENABLED=true
```

## Registry Server Configuration

> These variables configure the **Go registry server** (`mcp-mesh-registry`)

### Core Server Settings

```bash
# Server binding host
export HOST=localhost

# Server port
export PORT=8000

# Database connection URL
export DATABASE_URL=mcp_mesh_registry.db

# Registry service name
export REGISTRY_NAME=mcp-mesh-registry
```

### TLS and Security

```bash
# TLS mode: off, auto, or strict
export MCP_MESH_TLS_MODE=auto

# TLS certificate and key paths
export MCP_MESH_TLS_CERT=/path/to/cert.pem
export MCP_MESH_TLS_KEY=/path/to/key.pem
export MCP_MESH_TLS_CA=/path/to/ca.pem

# Trust backend: localca, filestore, k8s-secrets, spire
export MCP_MESH_TRUST_BACKEND=filestore

# Trust store directory (for filestore backend)
export MCP_MESH_TRUST_DIR=/path/to/trust/dir

# Admin port isolation (admin endpoints only on this port)
export MCP_MESH_ADMIN_PORT=8001

# Kubernetes secrets backend
export MCP_MESH_K8S_NAMESPACE=mcp-mesh
export MCP_MESH_K8S_LABEL_SELECTOR=mcp-mesh/trust-ca=true

# SPIRE integration
export MCP_MESH_SPIRE_SOCKET=/run/spire/sockets/agent.sock

# Agent TLS provider: file, spire, vault
export MCP_MESH_TLS_PROVIDER=file

# Vault PKI integration
export MCP_MESH_VAULT_ADDR=https://vault.example.com:8200
export MCP_MESH_VAULT_PKI_PATH=pki/issue/mcp-mesh
```

### Per-Service TLS

Configure TLS independently for each external service connection.
Each service reads `{PREFIX}_CA`, `{PREFIX}_CERT`, `{PREFIX}_KEY`, `{PREFIX}_SKIP_VERIFY`.

```bash
# UI → Registry proxy
export MCP_MESH_REGISTRY_TLS_CA=/path/to/ca.pem
export MCP_MESH_REGISTRY_TLS_CERT=/path/to/cert.pem
export MCP_MESH_REGISTRY_TLS_KEY=/path/to/key.pem
export MCP_MESH_REGISTRY_TLS_SKIP_VERIFY=false

# Redis
export REDIS_TLS_CA=/path/to/redis-ca.pem
export REDIS_TLS_CERT=/path/to/redis-cert.pem
export REDIS_TLS_KEY=/path/to/redis-key.pem
export REDIS_TLS_SKIP_VERIFY=false

# Tempo (HTTP query)
export TEMPO_TLS_CA=/path/to/tempo-ca.pem
export TEMPO_TLS_CERT=/path/to/tempo-cert.pem
export TEMPO_TLS_KEY=/path/to/tempo-key.pem

# OTLP/Telemetry (gRPC or HTTP exporter)
export TELEMETRY_TLS_CA=/path/to/otlp-ca.pem
export TELEMETRY_TLS_CERT=/path/to/otlp-cert.pem
export TELEMETRY_TLS_KEY=/path/to/otlp-key.pem
```

### Fast Heartbeat & Health Monitoring

```bash
# Agent heartbeat timeout - when to mark agents as unhealthy (seconds)
# Optimized for 5-second HEAD heartbeats: 4 missed beats = 20s
export DEFAULT_TIMEOUT_THRESHOLD=20

# Health monitor scan interval - how often to check for unhealthy agents (seconds)
export HEALTH_CHECK_INTERVAL=10

# Agent eviction threshold - when to remove stale agents (seconds)
export DEFAULT_EVICTION_THRESHOLD=60
```

### Registry Sweep / Retention

```bash
# How long unhealthy/unknown agents are kept in the registry before the
# sweep job purges them. Go duration string (e.g. "30m", "2h", "48h").
# Default: 1h. Set to "0" to disable the sweep entirely (forensic mode —
# keeps all rows). Affects `meshctl list` (purged agents disappear from
# output), the underlying RegistryEvent table (event rows are governed
# by a separate hardcoded 100,000 rolling cap, not by this variable),
# and orphan schema_entries (rows in the content-addressed schema store
# that are no longer referenced by any capability — purged when both
# orphan and older than this retention window; #842).
export MCP_MESH_RETENTION=1h
```

**Notes:**

- The sweep runs on a hardcoded 5-minute interval, so actual purge can
  lag retention by up to ~5 minutes.
- Setting `MCP_MESH_RETENTION` shorter than 5m (e.g. `1m`) will not
  speed up the purge cadence — it only affects when an agent becomes
  eligible for purge.
- Hardcoded internal constants: sweep interval = 5m, event hard cap =
  100,000 rows.

### Cache and Performance

```bash
# Response cache TTL (seconds)
export CACHE_TTL=30

# Enable response caching
export ENABLE_RESPONSE_CACHE=true
```

### Logging and Debug

```bash
# Registry log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export MCP_MESH_LOG_LEVEL=INFO

# Enable debug mode (true/false)
export MCP_MESH_DEBUG_MODE=false
```

### CORS Configuration

```bash
# Enable CORS support
export ENABLE_CORS=true

# Allowed origins (comma-separated)
export ALLOWED_ORIGINS="*"

# Allowed HTTP methods
export ALLOWED_METHODS="GET,POST,PUT,DELETE,OPTIONS"

# Allowed headers
export ALLOWED_HEADERS="*"

# Override CORS for a specific origin
export MCP_MESH_CORS_ORIGIN="http://localhost:3000"
```

### Feature Flags

```bash
# Enable metrics collection
export ENABLE_METRICS=true

# Enable Prometheus metrics
export ENABLE_PROMETHEUS=true

# Enable event system
export ENABLE_EVENTS=true

# Enable access logging
export ACCESS_LOG=true
```

## Proxy & Timeout

Agent-to-agent calls go through the registry proxy, which forwards the
request to the target agent. The `X-Mesh-Timeout` header controls how
long the proxy and SDK clients wait for a response. It propagates
automatically through multi-hop chains (gateway → planner → specialist).

```bash
# Registry proxy: default timeout in seconds when no X-Mesh-Timeout
# header is sent (default: 60s, capped at 600s)
export MCP_MESH_PROXY_TIMEOUT=60

# SDK: default timeout for outgoing mesh tool calls in seconds (default: 300s)
# SDKs send this as X-Mesh-Timeout header on outgoing calls, and use it to
# override the client-side HTTP timeout. Propagates down the call chain.
export MCP_MESH_CALL_TIMEOUT=300
```

**How timeout propagation works:**

1. First hop: SDK sets `X-Mesh-Timeout: 300` (from `MCP_MESH_CALL_TIMEOUT`) on the outgoing request
2. Registry proxy reads the header, uses it for its client timeout, and forwards it to the target agent
3. Target agent's SDK captures the header and propagates it on its own outgoing calls
4. The same timeout value flows through the entire chain without requiring per-hop configuration

If no `X-Mesh-Timeout` header is sent (e.g., a direct curl to an agent endpoint), the registry proxy falls back to `MCP_MESH_PROXY_TIMEOUT`.

```bash
# Example: raise proxy floor for an environment with long-running LLM chains
export MCP_MESH_PROXY_TIMEOUT=120
export MCP_MESH_CALL_TIMEOUT=600
```

## Tracing & Observability

### Distributed Tracing

```bash
# Enable distributed tracing
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true

# Redis URL for trace span streaming
export REDIS_URL=redis://localhost:6379

# Tempo HTTP query URL
export TEMPO_URL=http://localhost:3200

# OTLP endpoint (registry → Tempo)
export TELEMETRY_ENDPOINT=localhost:4317
export TELEMETRY_PROTOCOL=grpc          # grpc or http

# Trace exporter type: otlp, console, json
export TRACE_EXPORTER_TYPE=otlp

# Trace batching
export TRACE_BATCH_SIZE=100
export TRACE_TIMEOUT=5m

# Trace output options
export TRACE_PRETTY_OUTPUT=false
export TRACE_ENABLE_STATS=true
export TRACE_JSON_OUTPUT_DIR=/tmp/traces

# Alternative OTLP endpoint name
export OTLP_ENDPOINT=localhost:4317

# Redis trace publishing (agents)
export MCP_MESH_REDIS_TRACE_PUBLISHING=true
export MCP_MESH_TELEMETRY_ENABLED=true
```

### Header Propagation

```bash
# Comma-separated header prefixes to propagate across agent calls
export MCP_MESH_PROPAGATE_HEADERS=x-request-id,x-trace,x-correlation
```

### Stream Consumer

```bash
# Redis stream name for trace events
export STREAM_NAME=mesh:trace

# Consumer group name
export CONSUMER_GROUP=mcp-mesh-registry-processors
```

## UI Server

```bash
# UI server port
export MCP_MESH_UI_PORT=3080

# Registry URL for API proxy
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Base path for path-based ingress routing
export MCP_MESH_UI_BASE_PATH=/ops/dashboard

# Log level
export MCP_MESH_LOG_LEVEL=INFO
```

## LLM Configuration

### API Keys

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-your-key

# OpenAI
export OPENAI_API_KEY=sk-your-key

# Google Gemini AI Studio (API key — varies by runtime)
export GOOGLE_API_KEY=your-key                     # Python (via LiteLLM)
export GOOGLE_GENERATIVE_AI_API_KEY=your-key       # TypeScript (Vercel AI SDK)
export GOOGLE_AI_GEMINI_API_KEY=your-key           # Java (Spring AI)
```

For Gemini via Vertex AI (IAM auth), see the
[Vertex AI section below](#vertex-ai-gemini-via-iam) — env var conventions
also vary by runtime, with `GOOGLE_APPLICATION_CREDENTIALS` shared across
all three.

### Vertex AI (Gemini via IAM)

For users who want to call Gemini through Google Cloud's Vertex AI instead
of AI Studio (e.g., to use IAM service-account auth, GCP Provisioned
Throughput, VPC-SC, or org-controlled billing). All three runtimes share
mesh's `GeminiHandler` (same prompt-shaping, same HINT-mode behavior with
tools); only the auth transport and env var names differ.

#### Quick env var matrix

| Runtime    | SDK            | Project env var                              | Location env var                             |
| ---------- | -------------- | -------------------------------------------- | -------------------------------------------- |
| Python     | LiteLLM        | `VERTEXAI_PROJECT`                           | `VERTEXAI_LOCATION`                          |
| TypeScript | Vercel AI SDK  | `GOOGLE_VERTEX_PROJECT`                      | `GOOGLE_VERTEX_LOCATION`                     |
| Java       | Spring AI      | `SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID`<br/>(or set `spring.ai.vertex.ai.gemini.project-id`) | `SPRING_AI_VERTEX_AI_GEMINI_LOCATION`<br/>(or set `spring.ai.vertex.ai.gemini.location`) |

`GOOGLE_APPLICATION_CREDENTIALS` (or `gcloud auth application-default login`)
is the same across all three.

#### Python — model prefix

```python
@mesh.llm(
    provider={"capability": "llm", "tags": ["gemini"]},
    model="vertex_ai/gemini-2.0-flash",
)
async def my_tool(...): ...
```

The Python runtime routes `vertex_ai/*` through the same `GeminiHandler` as
`gemini/*`, but LiteLLM picks the Vertex AI transport based on the prefix.

Install the `vertex` extra (adds `google-auth`):

```bash
pip install 'mcp-mesh[vertex]'
```

Without it, the first Vertex call raises `ModuleNotFoundError: No module
named 'google.auth'`. (Non-Vertex users — AI Studio, Claude, OpenAI — don't
need this.)

LiteLLM auth resolution order:

1. Explicit `vertex_credentials` / `vertex_project` / `vertex_location`
   passed in the call (mesh does not set these — your env wins).
2. `VERTEXAI_CREDENTIALS` + `VERTEXAI_PROJECT` + `VERTEXAI_LOCATION`.
3. `GOOGLE_APPLICATION_CREDENTIALS` (standard ADC), with project/location
   derived from the SA JSON.
4. Implicit ADC (e.g., `gcloud` user credentials, GCE metadata server).

#### TypeScript — model prefix

```typescript
agent.addLlmProvider({
  model: "vertex_ai/gemini-2.0-flash",
  capability: "llm",
  tags: ["gemini", "vertex"],
});
```

`@ai-sdk/google-vertex` is bundled with `@mcpmesh/sdk` — no extra install.
Auth uses Google ADC. Both `GOOGLE_VERTEX_PROJECT` and `GOOGLE_VERTEX_LOCATION`
are required — the SDK throws a `LoadSettingError` on the first call if
either is unset (no project auto-discovery from ADC, no default location).
Common location values: `us-central1`, `global`.

#### Java — `provider = "vertex_ai"`

```java
@MeshLlm(provider = "vertex_ai", …)
@MeshTool(capability = "…")
public MyResult myTool(@Param("…") String input, MeshLlmAgent llm) { … }
```

Add the Vertex AI Spring AI starter to your `pom.xml` (mesh's
`mcp-mesh-spring-ai` does not pull it in by default):

```xml
<dependency>
  <groupId>org.springframework.ai</groupId>
  <artifactId>spring-ai-starter-model-vertex-ai-gemini</artifactId>
  <version>${spring-ai.version}</version>
</dependency>
```

Spring AI's Vertex AI auto-config doesn't read any conventional `GOOGLE_*`
env var on its own — it binds Spring Boot properties (which Spring relaxed
binding can populate from env vars):

| Spring property                                 | Env var (relaxed binding)                         |
| ----------------------------------------------- | ------------------------------------------------- |
| `spring.ai.vertex.ai.gemini.project-id`         | `SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID`           |
| `spring.ai.vertex.ai.gemini.location`           | `SPRING_AI_VERTEX_AI_GEMINI_LOCATION`             |
| `spring.ai.vertex.ai.gemini.chat.options.model` | `SPRING_AI_VERTEX_AI_GEMINI_CHAT_OPTIONS_MODEL`   |

`provider = "vertex_ai"` is significant: with just `provider = "gemini"`,
SpringAiLlmProvider prefers the AI Studio bean (`googleAiGeminiChatModel`)
when both backends are configured; `"vertex_ai"` forces the IAM path.

#### Same Code, Two Backends

The same agent code works against AI Studio _or_ Vertex AI by changing only
the model prefix / provider value and the auth config — no other code changes:

|                | AI Studio                                  | Vertex AI                                                          |
| -------------- | ------------------------------------------ | ------------------------------------------------------------------ |
| Python         | `model="gemini/gemini-2.0-flash"`          | `model="vertex_ai/gemini-2.0-flash"`                               |
| TypeScript     | `model: "gemini/gemini-2.0-flash"`         | `model: "vertex_ai/gemini-2.0-flash"`                              |
| Java           | `@MeshLlm(provider = "gemini")`            | `@MeshLlm(provider = "vertex_ai")`                                 |
| Auth env       | `GOOGLE_API_KEY` / `GOOGLE_GENERATIVE_AI_API_KEY` / `GOOGLE_AI_GEMINI_API_KEY` | `GOOGLE_APPLICATION_CREDENTIALS` (ADC)        |

#### Provisioned Throughput

GCP Provisioned Throughput is a Vertex AI account-side feature and requires
no mesh configuration — once your project has a PT reservation for the
target model, Vertex routes your calls through it automatically.

### LLM Agent Overrides

```bash
# Override LLM provider at runtime
export MESH_LLM_PROVIDER=openai          # claude, openai, anthropic
export MESH_LLM_MODEL=gpt-4o
export MESH_LLM_MAX_ITERATIONS=5
export MESH_LLM_FILTER_MODE=all          # all, include, exclude
```

### LLM Timeouts

```bash
# Provider call timeout (TypeScript, default: 300000ms)
export MESH_PROVIDER_TIMEOUT_MS=300000

# Individual tool timeout (TypeScript, default: 30000ms)
export MESH_TOOL_TIMEOUT_MS=30000

# LiteLLM proxy settings (Python)
export LITELLM_URL=http://localhost:4000
export LITELLM_TIMEOUT_MS=300000
```

## CLI & Development

```bash
# Watch mode settings
export MCP_MESH_RELOAD_DEBOUNCE=500       # File change debounce (ms)
export MCP_MESH_RELOAD_PORT_DELAY=500     # Port release delay after stop (ms)
export MCP_MESH_RELOAD_PRECHECK=true      # Syntax pre-check on reload

# Process management
export MCP_MESH_DB_PATH=mcp_mesh_registry.db
export MCP_MESH_STARTUP_TIMEOUT=30s
export MCP_MESH_SHUTDOWN_TIMEOUT=30s
export MCP_MESH_ENABLE_BACKGROUND=false
export MCP_MESH_PID_FILE=/path/to/pid

# Scaffold templates
export MESHCTL_TEMPLATE_DIR=/path/to/templates
```

## Database Tuning

```bash
# Connection pool
export DB_MAX_OPEN_CONNECTIONS=25
export DB_MAX_IDLE_CONNECTIONS=5
export DB_CONN_MAX_LIFETIME=30m
export DB_CONNECTION_TIMEOUT=30s

# SQLite-specific
export DB_BUSY_TIMEOUT=5000               # Busy timeout (ms)
export DB_JOURNAL_MODE=WAL
export DB_SYNCHRONOUS=NORMAL
export DB_CACHE_SIZE=-2000                # Negative = KB
export DB_ENABLE_FOREIGN_KEYS=true
```

## Internal

These variables are typically set automatically and rarely need manual configuration:

```bash
# Runtime version (for trace metadata)
export MCP_MESH_VERSION=1.1.0

# Native library path (Java)
export MESH_NATIVE_LIB_PATH=/usr/lib/mcp-mesh
```

## Media Storage

Configure the media storage backend for multimodal features.

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_MESH_MEDIA_STORAGE` | `local` | Storage backend: `local` or `s3` |
| `MCP_MESH_MEDIA_STORAGE_PATH` | `/tmp/mcp-mesh-media` | Local filesystem base path |
| `MCP_MESH_MEDIA_STORAGE_BUCKET` | `mcp-mesh-media` | S3 bucket name |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | _(none)_ | S3-compatible endpoint URL (for MinIO etc.) |
| `MCP_MESH_MEDIA_STORAGE_PREFIX` | `media/` | Key/directory prefix in storage |

### Example: Local Development

```bash
# Default — no configuration needed
export MCP_MESH_MEDIA_STORAGE=local
```

### Example: S3 with MinIO

```bash
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin
```

See [MediaStore Configuration](multimodal/media-store.md) for full details.

## Configuration Patterns

### Registry Server Configurations

#### Development Registry

```bash
# .env.registry.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
HOST=localhost
PORT=8000
DEFAULT_TIMEOUT_THRESHOLD=10  # Fast detection for development
HEALTH_CHECK_INTERVAL=5       # Quick scans for development
ENABLE_RESPONSE_CACHE=false   # Disable cache for testing
```

#### Production Registry

```bash
# .env.registry.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
HOST=0.0.0.0
PORT=8000
DEFAULT_TIMEOUT_THRESHOLD=20  # Balanced for production
HEALTH_CHECK_INTERVAL=10      # Regular monitoring
ENABLE_RESPONSE_CACHE=true
CACHE_TTL=30
DATABASE_URL=postgresql://user:pass@db:5432/mcp_mesh
```

#### High-Performance Registry

```bash
# .env.registry.high-perf
MCP_MESH_LOG_LEVEL=WARNING
DEFAULT_TIMEOUT_THRESHOLD=5   # Ultra-fast detection
HEALTH_CHECK_INTERVAL=2       # Very frequent monitoring
CACHE_TTL=60                  # Longer cache for performance
ENABLE_RESPONSE_CACHE=true
```

### Agent Development Environment

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_AUTO_RUN_INTERVAL=10
MCP_MESH_HEALTH_INTERVAL=15
```

### Production Environment

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=http://registry.company.com:8000
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
MCP_MESH_HTTP_HOST=api-service.company.com
```

### Testing Environment

```bash
# .env.testing
MCP_MESH_LOG_LEVEL=WARNING
MCP_MESH_DEBUG_MODE=false
MCP_MESH_AUTO_RUN=false
MCP_MESH_REGISTRY_URL=http://test-registry:8000
MCP_MESH_NAMESPACE=testing
```

## Using Environment Variables

### With Registry Server

```bash
# Start registry with environment file
mcp-mesh-registry --host 0.0.0.0 --port 8000

# Or with environment variables
DEFAULT_TIMEOUT_THRESHOLD=10 HEALTH_CHECK_INTERVAL=5 mcp-mesh-registry

# Load environment file manually
source .env.registry.development
mcp-mesh-registry

# Check registry configuration
mcp-mesh-registry --help
```

### With meshctl

```bash
# Load environment file
meshctl start my_agent.py --env-file .env.development

# Pass individual variables
meshctl start my_agent.py --env MCP_MESH_LOG_LEVEL=DEBUG --env MCP_MESH_DEBUG_MODE=true

# Use system environment
export MCP_MESH_LOG_LEVEL=DEBUG
meshctl start my_agent.py
```

### With Python

```bash
# Load environment file manually
source .env.development
python my_agent.py

# Or use python-dotenv in your agent
pip install python-dotenv
```

```python
import os
from dotenv import load_dotenv

# Load environment file
load_dotenv('.env.development')

# Your agent code here
```

### Override Agent Configuration

Environment variables override `@mesh.agent` decorator parameters:

```python
@mesh.agent(
    name="default-service",
    http_port=8080,
    auto_run=True,
    namespace="default"
)
class MyAgent:
    pass
```

```bash
# Override decorator settings
export MCP_MESH_AGENT_NAME=overridden-service
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_AUTO_RUN=false
export MCP_MESH_NAMESPACE=custom

# Runs with overridden values
python my_agent.py
```

## Advanced Configuration

### Kubernetes Environment

```bash
# Service discovery variables (auto-detected in K8s)
export SERVICE_NAME=my-service
export NAMESPACE=production
export POD_NAME=my-service-abc123
export POD_IP=10.244.1.5
export NODE_NAME=worker-node-1

# Namespace for trust backend (K8s secrets)
export MCP_MESH_K8S_NAMESPACE=mcp-mesh
export MCP_MESH_K8S_LABEL_SELECTOR="mcp-mesh.io/trust=entity-ca"

# Pod identity (injected by K8s downward API)
export POD_NAMESPACE=mcp-mesh
export HOSTNAME=my-agent-pod-abc123
```

### Docker Compose Environment

```yaml
# docker-compose.yml
services:
  my-agent:
    environment:
      - MCP_MESH_HTTP_HOST=my-agent # Service name for inter-container communication
      - MCP_MESH_HTTP_PORT=8080
      - MCP_MESH_REGISTRY_URL=http://registry:8000
      - MCP_MESH_LOG_LEVEL=INFO
      - MCP_MESH_NAMESPACE=docker
```

### Performance Tuning

```bash
# Python runtime optimization
export PYTHONUNBUFFERED=1
export PYTHONPATH=/app/lib:/app/agents

# Uvicorn server settings (for FastMCP)
export UVICORN_WORKERS=1
export UVICORN_LOOP=auto
export UVICORN_LIFESPAN=on
```

### Fast Heartbeat Optimization

Ultra-fast topology change detection:

```bash
# Ultra-aggressive (sub-5 second detection)
export DEFAULT_TIMEOUT_THRESHOLD=5   # Mark unhealthy after 5s
export HEALTH_CHECK_INTERVAL=2       # Scan every 2 seconds

# Balanced (default - sub-20 second detection)
export DEFAULT_TIMEOUT_THRESHOLD=20  # Mark unhealthy after 20s (4 missed 5s heartbeats)
export HEALTH_CHECK_INTERVAL=10      # Scan every 10 seconds

# Conservative (legacy behavior)
export DEFAULT_TIMEOUT_THRESHOLD=60  # Mark unhealthy after 60s
export HEALTH_CHECK_INTERVAL=30      # Scan every 30 seconds

# Production recommended
export DEFAULT_TIMEOUT_THRESHOLD=20
export HEALTH_CHECK_INTERVAL=10
```

**How it works:**

- Agents send lightweight HEAD requests every ~5 seconds
- Registry responds with topology change status (200/202/410)
- Background monitor detects unhealthy agents and creates events
- Other agents get notified via 202 responses on their HEAD checks

### Dynamic Updates

```bash
# Enable dynamic capability updates
export MCP_MESH_DYNAMIC_UPDATES=true

# Update strategy (immediate, graceful)
export MCP_MESH_UPDATE_STRATEGY=graceful

# Grace period for updates (seconds)
export MCP_MESH_UPDATE_GRACE_PERIOD=30
```

## Real-World Examples

### Multi-Service Development

```bash
# Terminal 1: Start registry with fast heartbeats
export MCP_MESH_LOG_LEVEL=DEBUG
export DEFAULT_TIMEOUT_THRESHOLD=10
export HEALTH_CHECK_INTERVAL=5
mcp-mesh-registry --host localhost --port 8000

# Terminal 2: Start auth service
export MCP_MESH_AGENT_NAME=auth-service
export MCP_MESH_HTTP_PORT=8081
export MCP_MESH_NAMESPACE=dev
export MCP_MESH_LOG_LEVEL=DEBUG
python services/auth.py

# Terminal 3: Start API service
export MCP_MESH_AGENT_NAME=api-service
export MCP_MESH_HTTP_PORT=8082
export MCP_MESH_NAMESPACE=dev
export MCP_MESH_LOG_LEVEL=DEBUG
python services/api.py
```

### Registry High Availability

```bash
# Primary registry (port 8000)
export HOST=0.0.0.0
export PORT=8000
export DATABASE_URL=postgresql://user:pass@primary-db:5432/mcp_mesh
export DEFAULT_TIMEOUT_THRESHOLD=20
export HEALTH_CHECK_INTERVAL=10
mcp-mesh-registry &

# Backup registry (port 8001) - read-only mode for failover
export HOST=0.0.0.0
export PORT=8001
export DATABASE_URL=postgresql://user:pass@replica-db:5432/mcp_mesh
export DEFAULT_TIMEOUT_THRESHOLD=30
export HEALTH_CHECK_INTERVAL=15
mcp-mesh-registry &
```

### Remote Registry Connection

```bash
# Connect to shared development registry
export MCP_MESH_REGISTRY_URL=http://dev-registry.team.local:8000
export MCP_MESH_NAMESPACE=shared-dev
export MCP_MESH_AGENT_NAME=my-feature-branch

python my_agent.py
```

### CI/CD Pipeline

```bash
# Test environment variables
export MCP_MESH_AUTO_RUN=false          # Don't auto-start in tests
export MCP_MESH_LOG_LEVEL=ERROR         # Minimal logging
export MCP_MESH_REGISTRY_URL=http://test-registry:8000
export MCP_MESH_NAMESPACE=ci-${BUILD_ID}

# Run tests
python -m pytest tests/
```

### Load Testing Setup

```bash
# Start multiple instances with unique names
for i in {1..5}; do
  export MCP_MESH_AGENT_NAME=load-test-agent-$i
  export MCP_MESH_HTTP_PORT=$((8080 + i))
  python my_agent.py &
done

# Monitor all instances
meshctl list --filter load-test
```

## Environment Variable Hierarchy

Environment variables are applied in this order (last wins):

1. **System environment variables**
2. **Environment files** (`.env`)
3. **meshctl `--env` flags**
4. **`@mesh.agent` decorator parameters**

```bash
# Example: Final port will be 9999
export MCP_MESH_HTTP_PORT=8080              # System (1)
# .env file has: MCP_MESH_HTTP_PORT=8081    # File (2)
meshctl start my_agent.py --env MCP_MESH_HTTP_PORT=9999  # Flag (3)
```

## Debugging Environment Issues

### Check Current Environment

```bash
# Show all MCP Mesh environment variables
env | grep MCP_MESH

# Test specific variable
echo $MCP_MESH_LOG_LEVEL

# Verify environment file loading
meshctl start my_agent.py --env-file .env.development --debug
```

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using a port
lsof -i :8080

# Use different port
export MCP_MESH_HTTP_PORT=8081
```

#### 2. Registry Connection Failed

```bash
# Test registry connectivity
curl -s http://localhost:8000/health

# Use different registry
export MCP_MESH_REGISTRY_URL=http://backup-registry:8000
```

#### 3. Agent Name Conflicts

```bash
# Use unique agent name
export MCP_MESH_AGENT_NAME=my-unique-agent-$(date +%s)

# Check existing agents
meshctl list
```

#### 4. Environment File Not Loaded

```bash
# Verify file exists and is readable
cat .env.development

# Use absolute path
meshctl start my_agent.py --env-file /full/path/to/.env.development
```

## Environment Templates

### Development Template

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_AUTO_RUN_INTERVAL=10
MCP_MESH_HEALTH_INTERVAL=15
MCP_MESH_HTTP_HOST=0.0.0.0
```

### Production Template

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=https://registry.company.com
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
MCP_MESH_UPDATE_STRATEGY=graceful
MCP_MESH_UPDATE_GRACE_PERIOD=60
MCP_MESH_HTTP_HOST=0.0.0.0
```

### Docker Template

```bash
# .env.docker
MCP_MESH_HTTP_HOST=my-service
MCP_MESH_REGISTRY_URL=http://registry:8000
MCP_MESH_NAMESPACE=docker
MCP_MESH_LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
```

## Security Considerations

### Sensitive Information

```bash
# ❌ Don't put secrets in environment files committed to git
MCP_MESH_API_KEY=secret123

# ✅ Use secure secret management
export MCP_MESH_API_KEY=$(kubectl get secret mesh-api-key -o jsonpath='{.data.key}' | base64 -d)

# ✅ Or use external secret providers
export MCP_MESH_REGISTRY_URL=$(vault kv get -field=url secret/mesh/registry)
```

### Network Security

```bash
# Use secure URLs in production
export MCP_MESH_REGISTRY_URL=https://registry.company.com  # ✅ HTTPS

# Bind the registry server to specific interfaces when needed
export HOST=127.0.0.1  # ✅ Localhost only
export HOST=0.0.0.0    # ⚠️ All interfaces (use carefully)
```

## Next Steps

Now that you understand environment configuration:

1. **[Local Development](./02-local-development.md)** - Professional development workflows
2. **[Production Deployment](./03-docker-deployment.md)** - Container orchestration
3. **[Mesh Decorators](./mesh-decorators.md)** - @mesh.tool, @mesh.llm decorators

---

## Summary

### Agent Configuration (Python)

Focus on `MCP_MESH_*` variables for agent behavior, heartbeat intervals, and service discovery.

### Registry Configuration (Go)

Focus on `DEFAULT_TIMEOUT_THRESHOLD` and `HEALTH_CHECK_INTERVAL` for fast topology detection.

---

💡 **Pro Tip**: Use environment files for different deployment stages - keeps configuration organized and secure.

🔧 **Development Tip**: Set `MCP_MESH_DEBUG_MODE=true` during development for detailed logging and faster feedback.

🚀 **Production Tip**: Use `DEFAULT_TIMEOUT_THRESHOLD=20` and `HEALTH_CHECK_INTERVAL=10` for optimal fast heartbeat performance.

⚡ **Performance Tip**: For ultra-fast systems, try `DEFAULT_TIMEOUT_THRESHOLD=5` and `HEALTH_CHECK_INTERVAL=2` for sub-5 second topology detection.

🛡️ **Registry Tip**: Use `DATABASE_URL` with PostgreSQL in production for better performance and reliability.
