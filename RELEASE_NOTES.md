# MCP Mesh Release Notes

## v0.4.2 (2025-08-11)

### 🔧 Critical Bug Fixes

**SSE Parsing Reliability**

- Fixed sporadic JSON parsing errors during large file processing (>15KB files)
- Consolidated duplicate SSE parsing logic across 3 proxy classes for improved maintainability
- Enhanced error handling with context-aware debugging for better troubleshooting
- Added shared `SSEParser` utility class with proper JSON accumulation logic

**FastMCP Discovery Stability**

- Fixed `RuntimeError: dictionary changed size during iteration` crashes during agent startup
- Applied thread-safe dictionary iteration patterns to prevent concurrent modification errors
- Improved startup reliability for complex multi-agent environments

**Code Consolidation**

- Eliminated duplicate SSE parsing code across `MCPClientProxy`, `AsyncMCPClient`, and `FullMCPProxy`
- Added `SSEStreamProcessor` for consistent streaming support
- Enhanced debugging capabilities with contextual logging

### 📁 New Files Added

- `src/runtime/python/_mcp_mesh/shared/sse_parser.py` - Consolidated SSE parsing utilities

### 🧪 Enhanced Examples

- Updated LLM chat agent with real Claude API integration and tool calling support
- New comprehensive chat client agent demonstrating advanced dependency injection patterns
- Improved large file processing examples with 100% reliability testing

### 📈 Validation Results

- ✅ **Large file processing**: 100% reliability with 23KB+ files generating 6K+ token responses
- ✅ **Agent startup**: Eliminated intermittent crashes during FastMCP server discovery
- ✅ **Code quality**: Consolidated duplicate logic improving maintainability and reducing technical debt
- ✅ **Testing**: Verified with real-world scenarios including rapid startup/shutdown cycles

---

## v0.4.1 (2025-08-10)

### 🏷️ Enhanced Tag Matching

**Smart Service Discovery**

- Enhanced tag matching with `+` (preferred) and `-` (excluded) operators
- Priority scoring system for intelligent provider selection
- Industry-standard syntax similar to Kubernetes label selectors

**Migration & Compatibility**

- Complete backward compatibility with existing exact tag matching
- Comprehensive migration guide and documentation updates
- Test-driven development with extensive unit test coverage

### 📚 Documentation

- Updated mesh decorators documentation with enhanced tag examples
- Migration guide for upgrading from exact matching to enhanced matching
- Smart LLM provider selection patterns with cost control examples

---

## v0.4.0 (2025-07-31)

### 🔍 Observability & Monitoring

**Complete Observability Stack**

- Full Grafana + Tempo integration for Kubernetes and Helm deployments
- Pre-configured dashboards with MCP Mesh branding and metrics
- Production-ready monitoring with persistent storage support

**Real-Time Trace Streaming**

- Live trace streaming API (`/traces/{trace_id}/stream`) with Server-Sent Events
- Watch multi-agent workflows execute in real-time through web dashboards
- Redis consumer groups for scalable trace data processing

**Distributed Tracing System**

- Redis streams integration for trace data storage (`mesh:trace` stream)
- OTLP export with direct protobuf generation for Tempo/Jaeger compatibility
- Cross-agent context propagation maintaining parent-child span relationships
- Complete observability directory structure with organized assets

### 🏗️ Architecture & Deployment

**Enhanced Kubernetes Support**

- New observability components in `k8s/base/observability/` and `examples/k8s/base/observability/`
- Distributed tracing environment variables for all agent deployments
- Complete Helm chart ecosystem with dedicated observability charts

**Multi-Agent Dependency Injection**

- Complex data processor example with modular tools and utilities
- Advanced agent architecture with parsing, transformation, analysis capabilities
- Comprehensive Docker containerization and development workflows

### ⚙️ Infrastructure Improvements

**Helm Chart Enhancements**

- New `mcp-mesh-grafana` and `mcp-mesh-tempo` charts
- Enhanced agent code deployment methods with improved configuration
- Comprehensive chart ecosystem for full-stack deployments

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
