# MCP-Mesh Developer CLI Requirements

## Week 1 Day 7: Developer Tools Implementation

### 🎯 **OVERVIEW**

This document defines the requirements for implementing the `mcp_mesh_dev` CLI tool based on the validated original design vision. The CLI serves as a simple process orchestrator that leverages the existing, production-ready mesh infrastructure to provide an intuitive development experience for MCP community developers.

**Important Note**: `pip install mcp_mesh` alone lets you run in MCP SDK environment, but will not have any MCP Mesh functionalities. Full mesh capabilities require `mcp_mesh_runtime` package.

### 📋 **CORE REQUIREMENTS**

#### **R1: Registry Service Management**

**R1.1 Registry Startup**

- CLI MUST start local registry service with SQLite backend
- Registry service MUST bind to configurable port (default: 8080)
- SQLite database MUST be automatically created and managed
- Registry MUST be accessible at `http://localhost:{port}`
- Registry startup MUST complete within 5 seconds

**R1.2 Registry Configuration**

- CLI MUST support `--registry-port` parameter for port configuration
- CLI MUST support `--db-path` parameter for SQLite database location
- Default SQLite location: `./dev_registry.db`
- CLI MUST handle port conflicts with automatic port selection
- Registry configuration MUST be persisted for session management

**R1.3 Registry Health Management**

- CLI MUST provide registry health status reporting
- CLI MUST detect registry availability before starting agents
- CLI MUST handle registry restart scenarios gracefully
- Registry MUST implement graceful shutdown on CLI stop commands

#### **R2: Agent Lifecycle Management**

**R2.1 Agent Startup Process**

- CLI MUST start individual Python agent files as separate processes
- Agent processes MUST receive `MCP_MESH_REGISTRY_URL` environment variable
- Agent startup MUST automatically trigger `@mesh_agent` registration
- Multiple agents MUST be able to run simultaneously
- Agent processes MUST be tracked with PIDs for management

**R2.2 Automatic Registry Integration**

- Registry service MUST be automatically started if not running when agent starts
- Agent registration MUST happen automatically via existing `@mesh_agent` decorator
- Function signature scanning MUST occur automatically (zero CLI involvement)
- Capability registration MUST happen without CLI intervention
- Health monitoring MUST be handled by existing heartbeat system

**R2.3 Agent Process Management**

- CLI MUST track all running agent processes
- CLI MUST provide process status for individual agents
- CLI MUST support graceful agent shutdown
- CLI MUST handle agent process cleanup on exit
- CLI MUST support agent restart with state preservation

#### **R3: Dynamic Dependency Injection Support**

**R3.1 Environment Configuration**

- CLI MUST set `MCP_MESH_REGISTRY_URL` environment variable for all agent processes
- Registry URL MUST be automatically determined based on running registry service
- Environment configuration MUST support custom registry URLs
- Agent processes MUST inherit proper environment for mesh integration

**R3.2 Real-time Dependency Updates**

- Dependency injection MUST work automatically via existing `@mesh_agent` implementation
- Parameter injection MUST occur when new services become available
- Parameter removal MUST occur when services become unavailable
- Heartbeat-based service eviction MUST work transparently
- No CLI intervention required for dependency management

**R3.3 Service Discovery Integration**

- Service discovery MUST work via existing registry client integration
- Agent capability updates MUST be handled by existing heartbeat system
- Registry state updates MUST propagate automatically to all agents
- Cache invalidation MUST occur via existing TTL mechanisms

#### **R4: Developer Experience**

**R4.1 Command Interface**

- CLI MUST provide intuitive command structure
- Commands MUST include: `start`, `stop`, `status`, `list`, `logs`
- Command-line help MUST be comprehensive and actionable
- Error messages MUST be helpful and provide guidance
- CLI MUST support both foreground and background operation modes

**R4.2 Help System and Documentation**

- CLI MUST provide comprehensive `--help` flag support
- Global help MUST be available via `mcp_mesh_dev --help`
- Command-specific help MUST be available via `mcp_mesh_dev <command> --help`
- Help text MUST include usage examples and common workflows
- Help system MUST follow standard CLI conventions (argparse/click patterns)
- Help text MUST be comprehensive enough for new users to get started

**R4.3 Status and Monitoring**

- CLI MUST show real-time status of registry and agents
- Process health information MUST be clearly displayed
- Registry connectivity status MUST be visible
- Agent registration status MUST be available
- Service discovery information MUST be accessible

**R4.4 Logging and Debugging**

- CLI MUST provide access to registry service logs
- CLI MUST provide access to individual agent logs
- Log filtering by service/agent MUST be supported
- Debug mode MUST provide verbose output for troubleshooting
- Log rotation and management MUST be handled appropriately

#### **R5: Integration Requirements**

**R5.1 Existing Infrastructure Integration**

- CLI MUST leverage existing `mcp_mesh_runtime` registry CLI entry point
- CLI MUST use existing `@mesh_agent` decorator functionality
- CLI MUST integrate with existing registry service implementation
- CLI MUST preserve all existing mesh capabilities and features
- No breaking changes to existing APIs MUST be introduced

**R5.2 Example Compatibility**

- CLI MUST work with all existing example files without modification
- Example execution MUST work seamlessly with CLI orchestration

#### **R6: Perfect Demonstration Example**

**R6.1 MCP vs MCP Mesh Capability Showcase**

- CLI MUST include perfect demonstration examples showcasing MCP vs MCP Mesh capabilities
- Demonstration MUST clearly show plain MCP behavior vs automatic dependency injection
- Examples MUST be simple, clear, and immediately understandable by new users
- Demonstration workflow MUST be documented and validated

**R6.2 Example Implementation Requirements**

- Example files MUST be provided in `examples/` directory
- `hello_world.py` MUST demonstrate both MCP-only and MCP Mesh functions
- `system_agent.py` MUST provide discoverable service for dependency injection
- Both examples MUST follow MCP SDK standards and existing project patterns
- HTTP endpoints MUST be properly implemented for curl testing
- **Important**: `pip install mcp_mesh` alone lets you run in MCP SDK environment, but will not have any MCP Mesh functionalities

**R6.3 Demonstration Workflow Validation**

- Single agent mode MUST show no dependency injection (plain MCP behavior)
- Multi-agent mode MUST show automatic dependency injection (MCP Mesh behavior)
- Real-time service discovery MUST be demonstrated through endpoint behavior changes
- Workflow MUST be reproducible and provide clear before/after comparison
- Documentation MUST guide users through complete demonstration

### 🔧 **TECHNICAL REQUIREMENTS**

#### **T1: CLI Installation and Executable Creation**

**T1.1 Python Entry Point Installation**

- CLI MUST be installable via `pip install` (development and production)
- CLI executable MUST be available immediately after installation
- CLI MUST use Python entry points via `pyproject.toml` `[project.scripts]` section
- Entry point MUST follow pattern: `mcp_mesh_dev = "mcp_mesh_runtime.cli.main:main"`
- CLI MUST be compatible with virtual environments and pip installation workflows

**T1.2 Cross-platform Executable Compatibility**

- CLI MUST work on Linux development environments (primary target)
- CLI MUST work on macOS development environments
- CLI SHOULD work on Windows development environments
- Python packaging system MUST handle platform-specific executable creation
- No separate shell scripts or bin/ directory files required
- Virtual environment integration MUST work seamlessly

**T1.3 Installation Methods Support**

- Development installation MUST work via `pip install -e .`
- Production installation MUST work via `pip install mcp_mesh_runtime`
- CLI changes MUST be reflected immediately in development mode
- CLI MUST integrate with existing package structure and entry points
- CLI MUST coexist with existing `mcp_mesh_runtime` server and registry commands

#### **T2: Process Management**

**T2.1 Subprocess Orchestration**

- Registry service MUST run as managed subprocess
- Agent processes MUST run as independent subprocesses
- Process monitoring MUST detect failures and provide restart capabilities
- Process cleanup MUST be reliable and complete
- Cross-platform compatibility MUST be maintained (Windows/Mac/Linux)

**T2.2 Environment Management**

- Environment variables MUST be properly set for all agent processes
- Registry URL propagation MUST be automatic and reliable
- Environment isolation MUST be maintained between agents
- Configuration overrides MUST be supported via environment variables

#### **T3: Configuration Management**

**T3.1 CLI Configuration**

- Default configuration MUST be embedded in CLI
- Configuration overrides MUST be supported via command-line arguments
- Configuration persistence MUST be available for development sessions
- Configuration validation MUST prevent invalid settings

**T3.2 Service Configuration**

- Registry port configuration MUST be dynamic and conflict-aware
- SQLite database location MUST be configurable
- Logging configuration MUST be adjustable
- Timeout and retry configurations MUST be accessible

#### **T4: Error Handling and Recovery**

**T4.1 Failure Scenarios**

- Registry startup failures MUST be handled gracefully
- Agent startup failures MUST provide clear error messages
- Port conflicts MUST be resolved automatically or with clear guidance
- Database access issues MUST be detected and reported
- Network connectivity issues MUST be handled with appropriate fallbacks

**T4.2 Recovery Mechanisms**

- Automatic retry logic MUST be implemented for transient failures
- Service restart capabilities MUST be available
- State recovery MUST preserve development session context
- Graceful degradation MUST be supported when components fail

### 🎪 **NON-REQUIREMENTS**

#### **Explicitly Out of Scope**

- Complex registration logic (handled by `@mesh_agent`)
- Function signature scanning (handled by `@mesh_agent`)
- Dependency injection implementation (handled by unified resolver)
- Service discovery logic (handled by existing registry client)
- Health monitoring implementation (handled by existing heartbeat system)
- Agent capability extraction (handled by existing metadata system)
- Production deployment features (covered by separate helm chart phase)
- Advanced security features beyond basic local development

### 📊 **PERFORMANCE REQUIREMENTS**

#### **P1: Startup Performance**

- Registry service startup: < 5 seconds
- Agent startup and registration: < 2 seconds
- CLI command response time: < 1 second
- Status query response time: < 500ms

#### **P2: Resource Usage**

- CLI memory overhead: < 50MB
- Registry service memory usage: < 200MB
- Agent process overhead: minimal (inherited from existing implementation)
- SQLite database size: reasonable for development workloads

#### **P3: Scalability**

- Support for 10+ concurrent agents in development
- Handle 100+ capability registrations
- Manage 1000+ dependency injections per minute
- Process 10+ agents starting/stopping per minute

### 🔐 **SECURITY REQUIREMENTS**

#### **S1: Local Development Security**

- Registry service MUST bind only to localhost by default
- SQLite database MUST have appropriate file permissions
- Agent processes MUST run with developer user permissions
- No sensitive data MUST be logged or exposed
- Environment variable handling MUST be secure

#### **S2: Process Isolation**

- Agent processes MUST be properly isolated
- Process cleanup MUST prevent resource leaks
- Signal handling MUST be secure and reliable
- File system access MUST respect standard permissions

### 🎯 **SUCCESS METRICS**

#### **Functional Metrics**

- 100% compatibility with existing examples
- Zero breaking changes to existing mesh APIs
- Complete original design vision implementation
- All acceptance criteria MUST be satisfied

#### **Developer Experience Metrics**

- New users can run examples in < 5 minutes
- CLI commands are discoverable and intuitive
- Error messages provide actionable guidance
- Development workflows are streamlined and efficient

#### **Technical Metrics**

- Process management is reliable and clean
- Service startup time meets performance requirements
- Memory usage stays within acceptable limits
- Cross-platform compatibility is maintained

---

## 📝 **IMPLEMENTATION NOTES**

### **Key Insights from Analysis**

- 95% of required functionality already exists in production-ready form
- CLI implementation is primarily process orchestration
- Complex mesh logic requires zero CLI involvement
- Original design vision perfectly aligns with existing infrastructure
- Implementation effort estimated at 2-3 days maximum

### **Critical Dependencies**

- Existing `mcp-mesh-registry` CLI entry point (✅ Available)
- Production-ready `@mesh_agent` decorator (✅ Validated)
- Complete registry service implementation (✅ Production-ready)
- Unified dependency resolver (✅ Revolutionary interface-optional system)
- Heartbeat-based health monitoring (✅ Fully implemented)

### **Executable Installation Strategy**

#### **Recommended Implementation Approach**

Based on research of modern Python CLI tools (pip, black, pytest, uvicorn, poetry), the recommended approach is:

1. **Use Python Entry Points** (Industry Standard):

   ```toml
   # pyproject.toml
   [project.scripts]
   mcp_mesh_dev = "mcp_mesh_runtime.cli.main:main"
   mcp_mesh_server = "mcp_mesh_runtime.server:main"
   mcp_mesh_registry = "mcp_mesh_runtime.server.registry_server:main"
   ```

2. **No bin/ Directory or Shell Scripts Needed**:

   - Modern Python packaging handles executable creation automatically
   - pip creates platform-appropriate wrappers (shell scripts on Linux/Mac, .exe on Windows)
   - Virtual environment integration works seamlessly
   - Cross-platform compatibility is automatic

3. **Installation Workflow**:

   ```bash
   # Development installation
   pip install -e .

   # Production installation
   pip install mcp-mesh

   # CLI immediately available
   mcp_mesh_dev --help
   ```

4. **Help System Implementation**:
   - Follow argparse/click patterns used by established tools
   - Comprehensive global help via `--help` flag
   - Command-specific help for all subcommands
   - Include usage examples in help text

#### **Why This Approach**

- **Industry Standard**: All major Python CLI tools use this pattern
- **Cross-platform**: pip handles Windows/Mac/Linux differences automatically
- **Virtual Environment Friendly**: Works seamlessly with development workflows
- **Zero Maintenance Overhead**: No shell scripts to maintain
- **Consistent with Project**: Matches existing entry points pattern

### **Package Structure Integration**

```
packages/mcp_mesh_runtime/src/mcp_mesh_runtime/
├── cli/                 # NEW: CLI implementation
│   ├── __init__.py
│   ├── main.py          # Entry point for mcp-mesh-dev
│   ├── commands/        # Command modules
│   └── utils.py         # CLI utilities
├── server/              # EXISTING: Server components
├── shared/              # EXISTING: Shared utilities
└── ...
```

### **Implementation Strategy**

Focus on developer experience and process management while leveraging 100% of existing, validated mesh infrastructure. The CLI should be a thin orchestration layer that makes the powerful mesh capabilities easily accessible to MCP community developers.
