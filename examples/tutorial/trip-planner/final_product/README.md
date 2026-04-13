# TripPlanner Final Product

A production-grade, mobile-first trip planning app backed by MCP Mesh agents.

- **Frontend**: React + Tailwind dark-mode UI with Google OAuth
- **Auth**: nginx/OpenResty with Lua-based session management (Redis-backed)
- **Backend**: 12 mesh agents (planner, budget analyst, adventure advisor, logistics, etc.)
- **Gateway**: FastAPI bridge between the UI and the mesh

## Architecture

```
Browser --> nginx (port 80)
              |-- /auth/*    --> Google OAuth (Lua)
              |-- /api/plan  --> gateway (port 8080) --> mesh agents
              |-- /*         --> SPA (React)
              |
           Redis (sessions + chat history)
```

## Prerequisites

- Node.js 18+
- Docker & Docker Compose
- Python 3.11+ with `mcp-mesh` installed
- Google OAuth credentials (or use DEV_MODE)

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your Google OAuth Client ID and Secret
# Or set DEV_MODE=true to bypass authentication
```

### 2. Build the UI

```bash
cd web
npm install
npm run build
cd ..
```

### 3. Start infrastructure (nginx + Redis)

```bash
docker compose up -d
```

### 4. Start the mesh agents

```bash
meshctl start --dte --debug -d -w \
  gateway \
  planner-agent \
  budget-analyst \
  adventure-advisor \
  logistics-planner \
  flight-agent \
  hotel-agent \
  weather-agent \
  poi-agent \
  user-prefs-agent \
  chat-history-agent \
  claude-provider
```

### 5. Open the app

```
http://localhost
```

## Development Mode

For local development without Google OAuth:

```bash
# In .env
DEV_MODE=true
```

This bypasses authentication and uses `demo@tripplanner.dev` as the user.

For hot-reload UI development:

```bash
cd web
npm run dev
# Opens on http://localhost:3001 with proxy to nginx on port 80
```

## Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `http://localhost/auth/callback`
4. Copy Client ID and Client Secret to `.env`

## Kubernetes Deployment

For production deployment on Kubernetes with SPIRE workload identity and mTLS:

```bash
cd k8s
./install.sh
```

This deploys the full stack:
- **SPIRE** server + agent for workload identity (`mcp-mesh.local` trust domain)
- **mcp-mesh-core** (registry, PostgreSQL, Redis, Tempo, Grafana) with SPIRE trust backend
- **13 mesh agents** with SPIRE mTLS (all inter-agent communication is mutually authenticated)
- **nginx** (OpenResty) with Google OAuth and SPA serving

See [`k8s/README.md`](k8s/README.md) for prerequisites, image build instructions, and customization.

### Building Agent Docker Images

Each agent directory contains a Dockerfile. Build and push to your registry before deploying:

```bash
REGISTRY="your-registry.example.com/trip-planner"
for agent in flight-agent hotel-agent weather-agent poi-agent \
             user-prefs-agent chat-history-agent claude-provider \
             openai-provider planner-agent gateway budget-analyst \
             adventure-advisor logistics-planner; do
  docker build -t $REGISTRY/$agent:latest ./$agent
  docker push $REGISTRY/$agent:latest
done
```

## Observability

For distributed tracing with Grafana + Tempo:

```bash
docker compose -f docker-compose.observability.yml up -d
```

Then set `MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true` when starting agents.
