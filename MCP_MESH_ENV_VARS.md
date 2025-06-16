# MCP Mesh Environment Variables

## Logging & Debug

- `MCP_MESH_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) - default: INFO
- `MCP_MESH_DEBUG_MODE`: Enable debug mode (true/false, 1/0, yes/no) - forces DEBUG level

## Registry Configuration

- `MCP_MESH_REGISTRY_URL`: Registry server URL - default: http://localhost:8000
- `MCP_MESH_REGISTRY_HOST`: Registry host - default: localhost
- `MCP_MESH_REGISTRY_PORT`: Registry port - default: 8000

## HTTP Configuration

- `MCP_MESH_HTTP_HOST`: HTTP server host - default: 0.0.0.0
- `MCP_MESH_HTTP_PORT`: HTTP server port - default: 8080
- `MCP_MESH_HTTP_ENABLED`: Enable HTTP transport (true/false) - default: auto
- `MCP_MESH_HTTP_ENDPOINT`: HTTP endpoint URL - default: auto-assigned
- `MCP_MESH_ENABLE_HTTP`: Enable HTTP for agents (true/false) - default: true

## Agent Configuration

- `MCP_MESH_AGENT_NAME`: Agent name override
- `MCP_MESH_NAMESPACE`: Agent namespace - default: default
- `MCP_MESH_ENABLED`: Enable MCP Mesh globally - default: true

## Auto-Run Configuration

- `MCP_MESH_AUTO_RUN`: Enable auto-run service (true/false) - default: auto-detect
- `MCP_MESH_AUTO_RUN_INTERVAL`: Auto-run heartbeat interval in seconds - default: 30

## Health & Monitoring

- `MCP_MESH_HEALTH_INTERVAL`: Health check interval in seconds - default: 30

## Update Strategy

- `MCP_MESH_DYNAMIC_UPDATES`: Enable dynamic updates - default: true
- `MCP_MESH_UPDATE_STRATEGY`: Update strategy (immediate, graceful) - default: immediate
- `MCP_MESH_UPDATE_GRACE_PERIOD`: Grace period for updates in seconds - default: 30

## MCP Endpoints

- `MCP_MESH_MCP_ENDPOINT`: MCP protocol endpoint - default: pending
