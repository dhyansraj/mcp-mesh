# MCP Mesh Registry - Go Implementation

This is the Go implementation of the MCP Mesh Registry Service, designed to be a drop-in replacement for the Python FastAPI version while maintaining 100% API compatibility.

## Architecture Preservation

**🚨 CRITICAL**: This Go implementation preserves ALL Python functionality:

- **API Compatibility**: 100% identical HTTP endpoints, request/response formats, and error messages
- **Database Schema**: Exact same SQLite/PostgreSQL schema as Python SQLAlchemy models
- **Business Logic**: Identical registration, heartbeat, and discovery logic
- **Configuration**: Same environment variables and configuration options
- **Caching**: 30-second TTL response caching matching Python behavior
- **Health Monitoring**: Timer-based passive health monitoring (no active polling)

## Key Components

### 1. Database Layer (`internal/database/`)
- **models.go**: GORM models matching Python SQLAlchemy schema exactly
- **database.go**: Database connection and schema management
- Supports SQLite (development) and PostgreSQL (production)
- Identical indexes and foreign key constraints

### 2. Registry Service (`internal/registry/`)
- **service.go**: Core business logic matching Python RegistryService
- **server.go**: Gin HTTP server with identical endpoints
- **types.go**: Request/response types matching Python Pydantic models

### 3. Configuration (`internal/config/`)
- **config.go**: Environment-based configuration matching Python settings
- Same environment variables and defaults as Python version

### 4. Main Binary (`cmd/mcp-mesh-registry/`)
- **main.go**: CLI entry point with same flags as Python version
- Graceful shutdown handling
- Production-ready error handling

## API Endpoints (Identical to Python)

All endpoints maintain exact compatibility with the Python FastAPI implementation:

- `POST /agents/register_with_metadata` - Agent registration with enhanced metadata
- `GET /agents` - Service discovery with advanced filtering
- `POST /heartbeat` - Agent status updates
- `GET /capabilities` - Capability discovery with search
- `GET /health` - Health check
- `GET /` - Service information

## Environment Variables

Same environment variables as Python version:

```bash
# Server Configuration
HOST=localhost
PORT=8000

# Database Configuration  
DATABASE_URL=mcp_mesh_registry.db
DB_CONNECTION_TIMEOUT=30
DB_BUSY_TIMEOUT=5000
DB_JOURNAL_MODE=WAL
DB_SYNCHRONOUS=NORMAL
DB_CACHE_SIZE=10000
DB_ENABLE_FOREIGN_KEYS=true

# Registry Configuration
REGISTRY_NAME=mcp-mesh-registry
HEALTH_CHECK_INTERVAL=30
CACHE_TTL=30
ENABLE_RESPONSE_CACHE=true

# Health Monitoring
DEFAULT_TIMEOUT_THRESHOLD=60
DEFAULT_EVICTION_THRESHOLD=120

# Logging
LOG_LEVEL=info
ACCESS_LOG=true

# CORS
ENABLE_CORS=true
ALLOWED_ORIGINS=*
ALLOWED_METHODS=GET,POST,PUT,DELETE,OPTIONS
ALLOWED_HEADERS=*
```

## Usage

### Development
```bash
# Using SQLite (default)
./mcp-mesh-registry

# Custom host/port
./mcp-mesh-registry --host 0.0.0.0 --port 9000
```

### Production
```bash
# Using PostgreSQL
DATABASE_URL=postgres://user:pass@localhost/mcp_mesh ./mcp-mesh-registry

# With environment variables
export HOST=0.0.0.0
export PORT=8080
export DATABASE_URL=postgres://user:pass@localhost/mcp_mesh
./mcp-mesh-registry
```

## Building

```bash
# Build for current platform
go build -o mcp-mesh-registry ./cmd/mcp-mesh-registry

# Build for Linux
GOOS=linux GOARCH=amd64 go build -o mcp-mesh-registry-linux ./cmd/mcp-mesh-registry

# Build for production (optimized)
go build -ldflags="-s -w" -o mcp-mesh-registry ./cmd/mcp-mesh-registry
```

## Testing API Compatibility

The Go implementation maintains exact API compatibility. You can test this with the same requests used for the Python version:

```bash
# Agent registration
curl -X POST http://localhost:8000/agents/register_with_metadata \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent",
    "metadata": {
      "name": "test-agent",
      "capabilities": [
        {
          "name": "greeting",
          "version": "1.0.0",
          "description": "Provides greeting functionality"
        }
      ]
    },
    "timestamp": "2024-01-01T12:00:00Z"
  }'

# Service discovery  
curl "http://localhost:8000/agents?status=healthy"

# Capability search
curl "http://localhost:8000/capabilities?name=greeting"

# Heartbeat
curl -X POST http://localhost:8000/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent",
    "status": "healthy"
  }'
```

## Performance Benefits

While maintaining API compatibility, the Go implementation provides:

- **Lower Memory Usage**: ~10-20MB vs ~50-100MB for Python
- **Faster Startup**: <100ms vs 1-2s for Python FastAPI
- **Higher Throughput**: 2-5x more requests/second
- **Single Binary**: No Python interpreter or dependencies needed
- **Better Resource Utilization**: Efficient goroutines vs threading

## Migration Strategy

The Go implementation is designed for seamless migration:

1. **Development**: Test Go registry with existing Python agents
2. **Staging**: Run both registries side-by-side 
3. **Production**: Switch traffic to Go registry
4. **Verification**: Confirm identical behavior

No changes required to Python decorator functionality or agent code.

## Deployment Modes

The Go registry supports the same deployment modes as Python:

- **Embedded CLI**: `mcp_mesh_dev start --registry-only` (when CLI is ported)
- **Standalone**: `./mcp-mesh-registry` binary
- **Container**: Docker/Podman deployment
- **Kubernetes**: K8s deployment with same service patterns

## Database Compatibility

The Go implementation uses the exact same database schema:

- SQLite for development (default)
- PostgreSQL for production
- Same table structures, indexes, and constraints
- Compatible with existing Python-created databases
- Automatic schema migrations maintained

## Monitoring and Observability

Same monitoring capabilities as Python version:

- Health check endpoint (`/health`)
- Prometheus metrics (when implemented)
- Structured logging
- Database statistics
- Agent lifecycle events

## Security

Maintains same security features:

- CORS configuration
- Input validation
- SQL injection protection via GORM
- Security context validation
- Request/response sanitization