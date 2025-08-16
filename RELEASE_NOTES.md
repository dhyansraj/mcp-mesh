# MCP Mesh Release Notes

## v0.5.2 (2025-08-16)

### 🍎 macOS Support & Platform Improvements

**Native macOS Binary Distribution**

- Added native macOS builds for both Intel (`darwin/amd64`) and Apple Silicon (`darwin/arm64`) architectures
- Implemented automated Homebrew tap distribution via `dhyansraj/homebrew-mcp-mesh`
- Fixed binary naming consistency: standardized on `mcp-mesh-registry` across all platforms
- Enhanced GitHub Actions pipeline with cross-platform build support and automated package manager updates

**Enhanced Installation Experience**

- **Homebrew Support**: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **PATH Resolution**: Improved binary discovery for both development and system installations using `exec.LookPath()`
- **Cross-Platform Install Script**: Updated `install.sh` to handle macOS/Linux differences seamlessly

**Distributed Tracing Reliability**

- Fixed silent tracing failures that were preventing proper observability data collection
- Enhanced FastAPI middleware integration for more robust trace capture
- Improved context handling and metadata publishing to Redis streams
- Updated Grafana dashboards with better trace visualization

### 🏷️ Migration Guide

**Upgrading from v0.5.1:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.2,<0.6"`
- **macOS Users**: Install via Homebrew: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **Docker Images**: Use `mcpmesh/registry:0.5.2` and `mcpmesh/python-runtime:0.5.2`
- **Helm Charts**: All charts now use v0.5.2 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.1
- Binary names are now consistent (`mcp-mesh-registry`) but old references will continue to work

### 📦 Distribution Improvements

- **GitHub Actions**: Native macOS builds with proper Gatekeeper signing preparation
- **Homebrew Automation**: Automatic formula updates with cross-platform checksum verification
- **Enhanced CI/CD**: Improved reliability with disabled Go cache and proper dependency management

---

## v0.5.1 (2025-08-14)

### 🔧 Major Enhancement Release - Unified Telemetry Architecture

**FastMCP Client Integration**

- Replaced custom MCP client with official FastMCP client library for better protocol compliance
- Enhanced error handling and timeout management with official client optimizations

**Unified Telemetry Architecture**

- Moved telemetry from HTTP middleware to dependency injection wrapper for complete coverage
- Added distributed tracing support for FastAPI routes with `@mesh.route()` decorators
- Unified agent ID generation across MCP agents and API services
- Redis stream storage for all telemetry data in `mesh:trace`

**Agent Context Enhancement**

- 3-step agent ID resolution: cached → @mesh.agent config → synthetic defaults
- Environment variable priority: `MCP_MESH_API_NAME` → `MCP_MESH_AGENT_NAME` → `api-{uuid8}`
- Comprehensive metadata collection with performance metrics

### 🏷️ Migration Guide

**Upgrading from v0.5.0:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.1,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5.1` and `mcpmesh/python-runtime:0.5.1`
- **Helm Charts**: All charts now use v0.5.1 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.0

---

## v0.5.0 (2025-08-13)

### 🚀 Major Release - FastAPI Dependency Injection Integration

**FastAPI Native Support**

- Complete FastAPI dependency injection system integration with MCP Mesh decorators
- Seamless interoperability between FastAPI's `Depends()` and mesh dependency resolution
- Type-safe dependency injection with automatic provider discovery and lifecycle management
- Introduced new `@mesh.route` decorator exclusively for FastAPI apps to inject MCP Mesh agents

**Advanced Dependency Resolution**

- Added +/- operator support in tags: + means preferred, - means exclude

### 🐛 Bug Fixes & Stability

- Enhanced support for large payload and response handling

### 🏷️ Migration Guide

**Upgrading from v0.4.x**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5` and `mcpmesh/python-runtime:0.5`
- **Helm Charts**: All charts now use v0.5.0 for consistent dependency management
- **Configuration**: Update any hardcoded version references in deployment manifests

**Breaking Changes**

- None - this release maintains full backward compatibility with v0.4.x
- Enhanced FastAPI integration is additive and does not affect existing code
- All existing decorators and patterns continue to work unchanged

---

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
