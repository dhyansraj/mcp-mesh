# Environment Variables

> Configure MCP Mesh via environment variables

## Overview

MCP Mesh can be configured using environment variables. They override `@mesh.agent` decorator parameters and provide flexibility for different deployment environments.

## Configuration Hierarchy

Configuration sources in order of precedence (highest wins):

1. Environment variables (system or `.env` files)
2. meshctl `--env` flags
3. `@mesh.agent` decorator parameters (lowest priority)

**Key point**: Environment variables override decorator parameters. This enables the same code to run locally (using decorator defaults) and in Kubernetes (using Helm-injected env vars) without modification.

## Agent Configuration

### Core Settings

```bash
# Agent identity
export MCP_MESH_AGENT_NAME=my-service
export MCP_MESH_NAMESPACE=production

# HTTP server
export HOST=0.0.0.0              # Bind address
export MCP_MESH_HTTP_PORT=8080   # Server port
export MCP_MESH_HTTP_HOST=my-service  # Announced hostname

# Auto-run behavior
export MCP_MESH_AUTO_RUN=true
export MCP_MESH_AUTO_RUN_INTERVAL=30  # Heartbeat interval (seconds)

# Health monitoring
export MCP_MESH_HEALTH_INTERVAL=30

# Global toggle
export MCP_MESH_ENABLED=true
```

### Registry Connection

```bash
# Full URL
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Or separate host/port
export MCP_MESH_REGISTRY_HOST=localhost
export MCP_MESH_REGISTRY_PORT=8000
```

### Logging

```bash
# Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
export MCP_MESH_LOG_LEVEL=INFO

# Debug mode (forces DEBUG level)
export MCP_MESH_DEBUG_MODE=true
```

### Advanced Settings

```bash
# HTTP server toggle
export MCP_MESH_HTTP_ENABLED=true

# External endpoint (for proxies/load balancers)
export MCP_MESH_HTTP_ENDPOINT=https://api.example.com:443

# Authentication token for secure communication
export MCP_MESH_AUTH_TOKEN=secret-token

# Startup debounce delay (seconds)
export MCP_MESH_DEBOUNCE_DELAY=1.0
```

### Schema Verdict Policy (issue #547)

```bash
# Cluster-wide schema strictness — when "true", agent treats schema-normalizer
# WARN verdicts as BLOCK and refuses to start. Default: false. Production
# hardening knob; per-tool output_schema_strict=false (Python) /
# outputSchemaStrict: false (TS) / outputSchemaStrict = false (Java)
# overrides this for that one tool.
export MCP_MESH_SCHEMA_STRICT=true
```

See `meshctl man schema-matching` for the verdict tiers and per-tool overrides.

## LLM Provider Configuration

Required for `@mesh.llm_provider` agents:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# OpenAI
export OPENAI_API_KEY=sk-your-key-here

# Google Gemini
export GOOGLE_API_KEY=your-gemini-key              # Python (via LiteLLM)
export GOOGLE_GENERATIVE_AI_API_KEY=your-key       # TypeScript (Vercel AI SDK)
export GOOGLE_AI_GEMINI_API_KEY=your-key           # Java (Spring AI)
```

### Vertex AI (Gemini via IAM)

For users who want to call Gemini through Google Cloud's Vertex AI instead of
AI Studio (IAM auth, GCP Provisioned Throughput, VPC-SC, org-controlled billing),
use the `vertex_ai/` model prefix (Python/TS) or `provider = "vertex_ai"` (Java).

All three runtimes share the same prompt-shaping rules — the same
GeminiHandler runs for both `gemini/*` and `vertex_ai/*`. Only the auth
transport and env var names differ.

#### Python (LiteLLM)

```python
@mesh.llm_provider(
    capability="llm",
    tags=["gemini", "vertex"],
    model="vertex_ai/gemini-2.0-flash",  # vs "gemini/gemini-2.0-flash" for AI Studio
)
def my_provider(): pass
```

Install the optional `vertex` extra (adds `google-auth` for ADC):

```bash
pip install 'mcp-mesh[vertex]'
```

| Scenario                                            | Required env vars                                                            |
| --------------------------------------------------- | ---------------------------------------------------------------------------- |
| User ADC (`gcloud auth application-default login`)  | `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION`                                      |
| Service account JSON                                | `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`, `VERTEXAI_LOCATION`       |
| Workload Identity (GKE pods)                        | `VERTEXAI_LOCATION` (project from WI binding)                                |

#### TypeScript (Vercel AI SDK)

```typescript
agent.addLlmProvider({
  model: "vertex_ai/gemini-2.0-flash",
  capability: "llm",
  tags: ["gemini", "vertex"],
});
```

`@ai-sdk/google-vertex` is bundled with `@mcpmesh/sdk` — no extra install
needed. Auth is via Google ADC.

| Scenario                                            | Required env vars                                                                |
| --------------------------------------------------- | -------------------------------------------------------------------------------- |
| User ADC (`gcloud auth application-default login`)  | `GOOGLE_VERTEX_PROJECT`, `GOOGLE_VERTEX_LOCATION`                                |
| Service account JSON                                | `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`, `GOOGLE_VERTEX_PROJECT`, `GOOGLE_VERTEX_LOCATION` |
| Workload Identity (GKE pods)                        | `GOOGLE_VERTEX_PROJECT`, `GOOGLE_VERTEX_LOCATION`                                |

Both `GOOGLE_VERTEX_PROJECT` and `GOOGLE_VERTEX_LOCATION` are required by
`@ai-sdk/google-vertex` — the SDK throws a `LoadSettingError` on the first
call if either is unset (it does not auto-discover the project from ADC and
has no default location). Common location values: `us-central1`, `global`.

#### Java (Spring AI)

```java
@MeshLlm(provider = "vertex_ai", …)
@MeshTool(capability = "…")
public MyResult myTool(@Param("…") String input, MeshLlmAgent llm) { … }
```

Add the Vertex AI starter to your `pom.xml` (mesh's `mcp-mesh-spring-ai`
keeps it optional so you don't pull google-cloud-aiplatform unless asked):

```xml
<dependency>
  <groupId>org.springframework.ai</groupId>
  <artifactId>spring-ai-starter-model-vertex-ai-gemini</artifactId>
  <version>${spring-ai.version}</version>
</dependency>
```

Spring AI's auto-config doesn't read any conventional `GOOGLE_*` env var on
its own — it binds Spring Boot properties:

| Spring property                              | Equivalent env var (relaxed binding)         |
| -------------------------------------------- | -------------------------------------------- |
| `spring.ai.vertex.ai.gemini.project-id`      | `SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID`      |
| `spring.ai.vertex.ai.gemini.location`        | `SPRING_AI_VERTEX_AI_GEMINI_LOCATION`        |
| `spring.ai.vertex.ai.gemini.chat.options.model` | `SPRING_AI_VERTEX_AI_GEMINI_CHAT_OPTIONS_MODEL` |

Auth is via Google ADC (`gcloud auth application-default login` or
`GOOGLE_APPLICATION_CREDENTIALS`).

The `provider = "vertex_ai"` value is significant. With just
`provider = "gemini"`, the runtime prefers the AI Studio bean
(`googleAiGeminiChatModel`) when both backends are configured;
`"vertex_ai"` forces the IAM path.

#### Common: ADC

ADC is auto-discovered from the standard Google location
(`~/.config/gcloud/application_default_credentials.json`) — no extra env
needed if you've run `gcloud auth application-default login`. For headless
or service-account scenarios, set `GOOGLE_APPLICATION_CREDENTIALS` to the
JSON key file path. This is the **same** across all three runtimes.

## LLM Agent Configuration

Override `@mesh.llm` decorator parameters at runtime:

```bash
# Override LLM provider (direct mode only, not mesh delegation)
# Values: claude, openai, anthropic
export MESH_LLM_PROVIDER=openai

# Override model
export MESH_LLM_MODEL=gpt-4o

# Override max agentic loop iterations
export MESH_LLM_MAX_ITERATIONS=5

# Override tool filter mode (all, include, exclude)
export MESH_LLM_FILTER_MODE=all
```

**Use case**: Same agent code, different LLM backends per environment:

```bash
# Development - use cheaper/faster model
meshctl start agent.py --env MESH_LLM_PROVIDER=openai --env MESH_LLM_MODEL=gpt-4o-mini

# Production - use Claude
meshctl start agent.py --env MESH_LLM_PROVIDER=claude --env MESH_LLM_MODEL=claude-sonnet-4-5
```

## Observability

```bash
# Distributed tracing (enable with single flag — all other defaults work)
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true

# Redis — trace span streaming (agents publish, registry + UI consume)
export REDIS_URL=redis://localhost:6379

# Tempo — trace storage and query
export TEMPO_URL=http://localhost:3200          # Tempo HTTP query API
export TELEMETRY_ENDPOINT=localhost:4317        # OTLP gRPC endpoint (registry → Tempo)
export TELEMETRY_PROTOCOL=grpc                  # OTLP protocol: grpc or http

# Trace exporter type: otlp, console, json (default: otlp)
export TRACE_EXPORTER_TYPE=otlp

# Header propagation across agents (comma-separated prefixes)
export MCP_MESH_PROPAGATE_HEADERS=x-request-id,x-trace

# UI server
export MCP_MESH_UI_PORT=3080                    # Dashboard server port

# UI base path for path-based ingress routing
export MCP_MESH_UI_BASE_PATH=/ops/dashboard
```

## Media Storage

Configure the storage backend for multimodal features (images, PDFs, files):

```bash
# Storage backend: "local" (default) or "s3"
export MCP_MESH_MEDIA_STORAGE=local

# Local filesystem settings
export MCP_MESH_MEDIA_STORAGE_PATH=/tmp/mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/

# S3 / S3-compatible settings (MinIO, AWS S3)
export MCP_MESH_MEDIA_STORAGE=s3
export MCP_MESH_MEDIA_STORAGE_BUCKET=mcp-mesh-media
export MCP_MESH_MEDIA_STORAGE_ENDPOINT=http://localhost:9000  # omit for AWS
export MCP_MESH_MEDIA_STORAGE_PREFIX=media/
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
```

| Variable                          | Default               | Description                      |
| --------------------------------- | --------------------- | -------------------------------- |
| `MCP_MESH_MEDIA_STORAGE`          | `local`               | Backend: `local` or `s3`         |
| `MCP_MESH_MEDIA_STORAGE_PATH`     | `/tmp/mcp-mesh-media` | Local filesystem base path       |
| `MCP_MESH_MEDIA_STORAGE_BUCKET`   | _(none)_              | S3 bucket name                   |
| `MCP_MESH_MEDIA_STORAGE_ENDPOINT` | _(none)_              | S3-compatible endpoint URL       |
| `MCP_MESH_MEDIA_STORAGE_PREFIX`   | `media/`              | Key/directory prefix             |
| `AWS_ACCESS_KEY_ID`               | _(none)_              | S3 access key (or use IAM roles) |
| `AWS_SECRET_ACCESS_KEY`           | _(none)_              | S3 secret key (or use IAM roles) |

In distributed deployments (Docker, Kubernetes), all agents that read or write media must share the same storage config. Use S3 for multi-container setups — `file://` URIs don't work across pods.

See `meshctl man media` for storage backend details and deployment guidance.

## Security & TLS

### TLS Configuration

```bash
# TLS mode
export MCP_MESH_TLS_MODE=auto           # off, auto, strict

# Certificate files (file provider)
export MCP_MESH_TLS_CERT=/etc/certs/agent.pem
export MCP_MESH_TLS_KEY=/etc/certs/agent-key.pem
export MCP_MESH_TLS_CA=/etc/certs/ca.pem

# Credential provider selection
export MCP_MESH_TLS_PROVIDER=file       # file, vault, spire
export MCP_MESH_TRUST_DOMAIN=mcp-mesh.local
```

### Vault Provider

```bash
export MCP_MESH_TLS_PROVIDER=vault
export MCP_MESH_VAULT_ADDR=https://vault.example.com:8200
export MCP_MESH_VAULT_PKI_PATH=pki_int/issue/mesh-agent
export VAULT_TOKEN=s.xxxxx
export MCP_MESH_VAULT_TTL=24h           # Certificate TTL (default: 24h)
```

### SPIRE Provider

```bash
export MCP_MESH_TLS_PROVIDER=spire
export MCP_MESH_SPIRE_SOCKET=/run/spire/agent/sockets/agent.sock
```

### Per-Service TLS

Configure TLS independently for each external service connection:

```bash
# UI → Registry proxy
export MCP_MESH_REGISTRY_TLS_CA=/path/to/ca.pem
export MCP_MESH_REGISTRY_TLS_CERT=/path/to/cert.pem
export MCP_MESH_REGISTRY_TLS_KEY=/path/to/key.pem

# Redis
export REDIS_TLS_CA=/path/to/redis-ca.pem
export REDIS_TLS_CERT=/path/to/redis-cert.pem
export REDIS_TLS_KEY=/path/to/redis-key.pem

# Tempo (HTTP query)
export TEMPO_TLS_CA=/path/to/tempo-ca.pem

# OTLP/Telemetry (gRPC exporter)
export TELEMETRY_TLS_CA=/path/to/otlp-ca.pem
```

### Registry Trust Backends

```bash
# Trust backend selection (comma-separated for chaining)
export MCP_MESH_TRUST_BACKEND=filestore        # localca, filestore, k8s-secrets, spire
export MCP_MESH_TRUST_DIR=/etc/mcp-mesh/trust

# K8s secrets backend
export MCP_MESH_K8S_NAMESPACE=mcp-mesh
export MCP_MESH_K8S_LABEL_SELECTOR="mcp-mesh.io/trust=entity-ca"

# SPIRE backend
export MCP_MESH_SPIRE_SOCKET=/run/spire/agent/sockets/agent.sock

# Admin port isolation
export MCP_MESH_ADMIN_PORT=9443
```

## Proxy & Timeout

```bash
# Default proxy timeout in seconds when no X-Mesh-Timeout header is sent (default: 60)
export MCP_MESH_PROXY_TIMEOUT=60

# Default timeout for outgoing mesh tool calls in seconds (default: 300)
# SDKs send this as X-Mesh-Timeout header on outgoing calls
export MCP_MESH_CALL_TIMEOUT=300
```

## Registry Configuration

```bash
# Server binding
export HOST=0.0.0.0
export PORT=8000

# Database
export DATABASE_URL=mcp_mesh_registry.db  # SQLite
export DATABASE_URL=postgresql://user:pass@host:5432/db  # PostgreSQL

# Health monitoring
export DEFAULT_TIMEOUT_THRESHOLD=20   # Mark unhealthy (seconds)
export HEALTH_CHECK_INTERVAL=10       # Scan frequency (seconds)
export DEFAULT_EVICTION_THRESHOLD=60  # Evict stale agents (seconds)

# Caching
export CACHE_TTL=30
export ENABLE_RESPONSE_CACHE=true

# CORS
export ENABLE_CORS=true
export ALLOWED_ORIGINS="*"
# CORS origin override (alternative to ALLOWED_ORIGINS)
export MCP_MESH_CORS_ORIGIN="http://localhost:3000"

# Features
export ENABLE_METRICS=true
export ENABLE_PROMETHEUS=true
```

## Environment Profiles

### Development

```bash
# .env.development
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_NAMESPACE=development
MCP_MESH_AUTO_RUN_INTERVAL=10
MCP_MESH_HEALTH_INTERVAL=15
HOST=0.0.0.0
```

### Production

```bash
# .env.production
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_REGISTRY_URL=https://registry.company.com
MCP_MESH_NAMESPACE=production
MCP_MESH_AUTO_RUN_INTERVAL=30
MCP_MESH_HEALTH_INTERVAL=30
HOST=0.0.0.0

# TLS (choose one provider)
MCP_MESH_TLS_MODE=strict
MCP_MESH_TLS_PROVIDER=vault
MCP_MESH_VAULT_ADDR=https://vault.company.com:8200
MCP_MESH_VAULT_PKI_PATH=pki_int/issue/mesh-agent
```

### Testing

```bash
# .env.testing
MCP_MESH_LOG_LEVEL=WARNING
MCP_MESH_AUTO_RUN=false
MCP_MESH_REGISTRY_URL=http://test-registry:8000
MCP_MESH_NAMESPACE=testing
```

## Using Environment Files

### With meshctl

```bash
meshctl start my_agent.py --env-file .env.development

# Individual variables
meshctl start my_agent.py --env MCP_MESH_LOG_LEVEL=DEBUG
```

### With Python

```bash
source .env.development
python my_agent.py

# Or use python-dotenv
pip install python-dotenv
```

```python
from dotenv import load_dotenv
load_dotenv('.env.development')
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
  - name: MCP_MESH_AGENT_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
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

## Debugging

```bash
# Show all MCP Mesh environment variables
env | grep MCP_MESH

# Test specific variable
echo $MCP_MESH_LOG_LEVEL

# Verify with meshctl
meshctl start my_agent.py --env-file .env.dev --debug
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

### Agent Name Conflicts

```bash
export MCP_MESH_AGENT_NAME=my-unique-agent-$(date +%s)
meshctl list
```

## Full Reference

For the complete list of all environment variables (50+ additional vars for database tuning, Kubernetes, internal settings, and more), see the full documentation:

> https://mcp-mesh.ai/environment-variables

## See Also

- `meshctl man deployment` - Deployment patterns
- `meshctl man registry` - Registry configuration
- `meshctl man health` - Health monitoring settings
