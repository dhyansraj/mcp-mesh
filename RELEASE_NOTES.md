# MCP Mesh Release Notes

## v0.3.0 (2025-07-04)

### 🚀 Major Features

**Enhanced Proxy System**

- Automatic proxy configuration from decorator kwargs (timeout, retry_count, custom_headers)
- Smart proxy selection based on capability requirements
- Authentication and streaming auto-configuration

**Redis-Backed Session Management**

- Distributed session storage with graceful in-memory fallback
- Session stickiness for stateful applications
- Automatic routing to same pod instances

**Advanced Agent Types**

- `McpMeshAgent`: Lightweight proxies for simple tool calls
- `McpAgent`: Full MCP protocol support with streaming and session management
- Backward compatibility maintained

**Streaming Support**

- `call_tool_streaming()` for real-time data processing
- FastMCP integration with text/event-stream
- Multihop streaming capabilities

### ⚡ Performance & Infrastructure

**Fast Heartbeat Optimization**

- 5-second heartbeat intervals with HEAD request optimization
- Sub-20 second topology change detection
- Improved fault tolerance and recovery

**Kubernetes Native**

- Comprehensive ingress support eliminates port forwarding
- Agent status management with graceful shutdown
- Enhanced health check endpoints

**Architecture Improvements**

- Registry as facilitator pattern
- Direct agent-to-agent communication
- Background orchestration with minimal overhead

### 📚 Developer Experience

**Enhanced Documentation**

- Comprehensive mesh decorator examples
- Clear distinction between agent types
- Advanced usage patterns and best practices

**Improved CLI**

- Better startup performance
- Enhanced error messages
- Environment variable consistency

### 🔧 Technical Improvements

- Ent migration completion (removed GORM/SQL remnants)
- Dependency resolution optimization
- Tag handling consistency fixes
- Python runtime cleanup

---

## v0.2.1 (2025-07-01)

### 🐛 Bug Fixes

- Fix Python packaging source paths in release workflow
- Resolve version update path issues
- Address DecoratorRegistry gaps and environment variable consistency

### 📦 Infrastructure

- Complete MCP Mesh 0.2.0 release preparation
- Add HEAD method support for efficient health checks
- Optimize CLI startup and FastAPI termination performance

---

## v0.1.0 (2025-06-19)

### 🎯 Initial Release

- Core dependency injection system
- Kubernetes deployment support
- Basic agent discovery and communication
- FastMCP integration
- Docker and Helm chart support
