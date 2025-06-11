# MCP-Mesh Developer CLI Acceptance Criteria
## Week 1 Day 7: Developer Tools Implementation

### 🎯 **OVERVIEW**

This document defines the comprehensive acceptance criteria for the `mcp-mesh-dev` CLI tool implementation. These criteria validate that the original design vision is fully implemented and that the CLI provides an excellent developer experience for the MCP community.

### ✅ **AC1: CLI Installation and Help System**

#### **AC1.1: Python Entry Point Installation**
- [ ] **MUST**: `pip install -e .` installs CLI executable successfully
- [ ] **MUST**: `mcp-mesh-dev` command is available in PATH after installation
- [ ] **MUST**: CLI entry point is defined in `pyproject.toml` `[project.scripts]` section
- [ ] **MUST**: CLI coexists with existing `mcp-mesh-server` and `mcp-mesh-registry` commands
- [ ] **MUST**: CLI works in virtual environments and development installations

**Validation Commands**: 
```bash
pip install -e .
which mcp-mesh-dev
mcp-mesh-dev --version
```
**Expected Result**: CLI installed and accessible as system command

#### **AC1.2: Comprehensive Help System**
- [ ] **MUST**: `mcp-mesh-dev --help` shows comprehensive global help
- [ ] **MUST**: Global help includes program description, available commands, and usage examples
- [ ] **MUST**: Command-specific help available via `mcp-mesh-dev <command> --help`
- [ ] **MUST**: Help text includes original design vision workflow examples
- [ ] **MUST**: Help system follows standard CLI conventions (argparse patterns)
- [ ] **MUST**: Help content enables new users to get started in < 5 minutes

**Validation Commands**:
```bash
mcp-mesh-dev --help
mcp-mesh-dev start --help
mcp-mesh-dev stop --help
mcp-mesh-dev status --help
```
**Expected Result**: Comprehensive, actionable help text for all commands

#### **AC1.3: Cross-platform Compatibility**
- [ ] **MUST**: CLI works on Linux development environments
- [ ] **SHOULD**: CLI works on macOS development environments  
- [ ] **SHOULD**: CLI works on Windows development environments
- [ ] **MUST**: Python packaging system handles platform-specific executable creation
- [ ] **MUST**: No manual shell scripts or bin/ directory files required

**Validation Method**: Test installation and execution on multiple platforms
**Expected Result**: CLI works seamlessly across target platforms

### ✅ **AC2: Basic Service Management**

#### **AC2.1: Registry Service Startup**
- [ ] **MUST**: `mcp-mesh-dev start` launches registry service successfully
- [ ] **MUST**: Registry binds to default port 8080 or specified `--registry-port`
- [ ] **MUST**: SQLite database is created automatically at `./dev_registry.db` or `--db-path`
- [ ] **MUST**: Registry startup completes within 5 seconds
- [ ] **MUST**: Registry service health endpoint responds at `http://localhost:{port}/health`

**Validation Command**: `mcp-mesh-dev start`
**Expected Result**: Registry service starts, SQLite database created, health endpoint accessible

#### **AC2.2: Registry Service Status**
- [ ] **MUST**: `mcp-mesh-dev status` shows accurate registry health
- [ ] **MUST**: Status displays registry port, database location, and health status
- [ ] **MUST**: Status indicates when registry is not running
- [ ] **MUST**: Status command responds within 1 second

**Validation Command**: `mcp-mesh-dev status`
**Expected Result**: Clear status display showing registry health and configuration

#### **AC2.3: Registry Service Shutdown**
- [ ] **MUST**: `mcp-mesh-dev stop` shuts down registry service gracefully
- [ ] **MUST**: Registry process cleanup is complete and reliable
- [ ] **MUST**: SQLite database is properly closed and not corrupted
- [ ] **MUST**: No zombie processes remain after shutdown

**Validation Command**: `mcp-mesh-dev stop`
**Expected Result**: Registry shuts down gracefully, no process leaks

#### **AC2.4: Background Operation**
- [ ] **MUST**: `mcp-mesh-dev start -d` launches registry in background
- [ ] **MUST**: Background registry continues running after CLI exit
- [ ] **MUST**: CLI can reconnect to existing background registry
- [ ] **MUST**: Background processes are trackable and manageable

**Validation Command**: `mcp-mesh-dev start -d && mcp-mesh-dev status`
**Expected Result**: Registry runs in background, status shows running service

#### **AC2.5: Multiple Start/Stop Cycles**
- [ ] **MUST**: Multiple consecutive starts/stops work without conflicts
- [ ] **MUST**: Port conflicts are detected and handled gracefully
- [ ] **MUST**: Database locks are properly managed across restarts
- [ ] **MUST**: Process state is accurately tracked across cycles

**Validation Commands**: Multiple `mcp-mesh-dev start` and `stop` commands
**Expected Result**: Reliable operation across multiple cycles

### ✅ **AC3: Agent Lifecycle Management**

#### **AC3.1: Original Design Vision - Intent Agent First**
- [ ] **MUST**: `mcp-mesh-dev start intent_agent.py` works end-to-end
- [ ] **MUST**: Registry service starts automatically if not running
- [ ] **MUST**: Intent agent process starts successfully
- [ ] **MUST**: `@mesh_agent` decorator automatically scans and registers functions
- [ ] **MUST**: Agent registration appears in registry within 2 seconds
- [ ] **MUST**: No dependency parameters are injected (first agent scenario)

**Validation Commands**:
```bash
mcp-mesh-dev start examples/intent_agent.py
mcp-mesh-dev list
mcp-mesh-dev logs intent_agent.py
```
**Expected Result**: Intent agent runs, registers capabilities, no dependency injection

#### **AC2.2: Original Design Vision - Developer Agent Second**
- [ ] **MUST**: `mcp-mesh-dev start developer_agent.py` triggers dependency injection
- [ ] **MUST**: Developer agent registers capabilities with registry
- [ ] **MUST**: Intent agent detects developer agent via heartbeat updates
- [ ] **MUST**: Intent agent receives dependency-injected parameters for developer agent
- [ ] **MUST**: Real-time dependency injection occurs without CLI intervention

**Validation Commands**:
```bash
# (Intent agent already running from AC2.1)
mcp-mesh-dev start examples/developer_agent.py
mcp-mesh-dev list
mcp-mesh-dev logs intent_agent.py  # Should show dependency injection
```
**Expected Result**: Developer agent starts, intent agent gets dependency injection

#### **AC2.3: Original Design Vision - Service Eviction**
- [ ] **MUST**: `mcp-mesh-dev stop developer_agent.py` removes dependency injection
- [ ] **MUST**: Developer agent heartbeat stops, triggering registry eviction
- [ ] **MUST**: Intent agent loses developer agent dependency parameters
- [ ] **MUST**: Intent agent continues running without developer dependencies
- [ ] **MUST**: Registry state reflects developer agent removal

**Validation Commands**:
```bash
mcp-mesh-dev stop developer_agent.py
mcp-mesh-dev list
mcp-mesh-dev logs intent_agent.py  # Should show dependency removal
```
**Expected Result**: Developer agent stops, intent agent loses dependency injection

#### **AC2.4: Multiple Agent Management**
- [ ] **MUST**: Multiple agents can run simultaneously
- [ ] **MUST**: Each agent can be stopped independently
- [ ] **MUST**: Agent process isolation is maintained
- [ ] **MUST**: Registry state accurately reflects all running agents

**Validation Commands**:
```bash
mcp-mesh-dev start agent1.py
mcp-mesh-dev start agent2.py
mcp-mesh-dev start agent3.py
mcp-mesh-dev list
mcp-mesh-dev stop agent2.py
mcp-mesh-dev list
```
**Expected Result**: Multiple agents run independently, selective shutdown works

#### **AC2.5: Agent Restart with State Preservation**
- [ ] **MUST**: `mcp-mesh-dev restart <agent.py>` preserves registry state
- [ ] **MUST**: Agent capabilities are re-registered after restart
- [ ] **MUST**: Dependency relationships are restored after restart
- [ ] **MUST**: Other agents maintain connections during restart

**Validation Commands**:
```bash
mcp-mesh-dev restart intent_agent.py
mcp-mesh-dev status
mcp-mesh-dev list
```
**Expected Result**: Agent restarts successfully, maintains registry integration

### ✅ **AC3: Dynamic Dependency Injection Validation**

#### **AC3.1: Automatic Function Signature Scanning**
- [ ] **MUST**: Agent functions are automatically scanned via `@mesh_agent`
- [ ] **MUST**: Method signatures are extracted and registered with registry
- [ ] **MUST**: Capability metadata includes function signature information
- [ ] **MUST**: Registry reflects all agent capabilities and methods

**Validation Method**: Check registry API for agent capabilities and method signatures
**Expected Result**: Complete function metadata available in registry

#### **AC3.2: Real-time Dependency Resolution Updates**
- [ ] **MUST**: Dependency injection updates occur within 30 seconds (heartbeat interval)
- [ ] **MUST**: New service availability triggers parameter injection
- [ ] **MUST**: Service unavailability triggers parameter removal
- [ ] **MUST**: Dependency resolution happens without CLI intervention

**Validation Method**: Monitor agent logs during service addition/removal
**Expected Result**: Real-time dependency updates reflected in agent behavior

#### **AC3.3: Heartbeat-based Service Eviction**
- [ ] **MUST**: Heartbeat mechanism works for automatic service eviction
- [ ] **MUST**: Services are marked as degraded when heartbeats are late
- [ ] **MUST**: Services are evicted when heartbeats stop completely
- [ ] **MUST**: Registry state updates propagate to all connected agents

**Validation Method**: Kill agent process directly (bypass CLI) and monitor registry
**Expected Result**: Automatic eviction occurs, dependent agents lose parameters

#### **AC3.4: Dependency Cache and Performance**
- [ ] **MUST**: Dependency resolution uses efficient caching (5-minute TTL)
- [ ] **MUST**: Cache invalidation occurs on service changes
- [ ] **MUST**: Dependency resolution completes within 200ms
- [ ] **MUST**: Concurrent dependency resolution works reliably

**Validation Method**: Performance testing with multiple dependencies
**Expected Result**: Fast, reliable dependency resolution with proper caching

### ✅ **AC4: Example Integration and Compatibility**

#### **AC4.1: Existing Example Compatibility**
- [ ] **MUST**: All 16 existing examples work with `mcp-mesh-dev start <example>`
- [ ] **MUST**: Examples require zero code modifications
- [ ] **MUST**: Examples demonstrate mesh features when run via CLI
- [ ] **MUST**: FastMCP dual-decorator pattern works correctly

**Validation Commands**: Test each example file individually
**Expected Result**: All examples run successfully without modification

#### **AC4.2: Example Validation**
- [ ] **MUST**: `mcp-mesh-dev validate <agent.py>` catches common issues
- [ ] **MUST**: Validation detects missing `@mesh_agent` decorators
- [ ] **MUST**: Validation checks Python syntax and import errors
- [ ] **MUST**: Validation provides helpful suggestions for fixes

**Validation Commands**:
```bash
mcp-mesh-dev validate examples/intent_agent.py
mcp-mesh-dev validate broken_agent.py  # Intentionally broken
```
**Expected Result**: Validation provides useful feedback on agent files

#### **AC4.3: Interactive Demo Mode**
- [ ] **MUST**: `mcp-mesh-dev demo <agent>` provides interactive experience
- [ ] **SHOULD**: Demo mode shows step-by-step mesh integration
- [ ] **SHOULD**: Demo mode demonstrates dependency injection in real-time
- [ ] **SHOULD**: Demo mode provides educational value for learning mesh concepts

**Validation Commands**: `mcp-mesh-dev demo file_agent`
**Expected Result**: Interactive demonstration of mesh capabilities

### ✅ **AC5: Developer Experience**

#### **AC5.1: CLI Usability**
- [ ] **MUST**: CLI commands are intuitive and self-documenting
- [ ] **MUST**: `mcp-mesh-dev --help` provides comprehensive usage information
- [ ] **MUST**: Command-specific help is available via `<command> --help`
- [ ] **MUST**: Error messages are helpful and provide actionable guidance

**Validation Method**: User experience testing with new developers
**Expected Result**: Intuitive command structure with excellent help system

#### **AC5.2: Error Handling and Recovery**
- [ ] **MUST**: Port conflicts produce clear error messages with solutions
- [ ] **MUST**: Missing dependencies provide helpful installation guidance
- [ ] **MUST**: Agent startup failures include diagnostic information
- [ ] **MUST**: Registry connectivity issues provide troubleshooting steps

**Validation Method**: Simulate various error conditions
**Expected Result**: Clear, actionable error messages for all failure scenarios

#### **AC5.3: Logging and Debugging**
- [ ] **MUST**: `mcp-mesh-dev logs` shows aggregated service logs
- [ ] **MUST**: `mcp-mesh-dev logs <service>` shows specific service logs
- [ ] **MUST**: Debug mode (`--debug`) provides verbose output
- [ ] **MUST**: Log output is formatted clearly and includes timestamps

**Validation Commands**:
```bash
mcp-mesh-dev logs
mcp-mesh-dev logs registry
mcp-mesh-dev logs intent_agent.py
mcp-mesh-dev --debug start intent_agent.py
```
**Expected Result**: Comprehensive logging with good formatting and filtering

#### **AC5.4: Status and Monitoring**
- [ ] **MUST**: Status output is clear and actionable
- [ ] **MUST**: Process health information is accurately displayed
- [ ] **MUST**: Registry connectivity status is visible
- [ ] **MUST**: Service discovery information is accessible

**Validation Commands**: `mcp-mesh-dev status` with various system states
**Expected Result**: Clear, informative status display

### ✅ **AC6: Perfect Demonstration Example Validation**

#### **AC6.1: MCP vs MCP Mesh Capability Showcase**
- [ ] **MUST**: Perfect demonstration examples exist in `samples/` directory
- [ ] **MUST**: `hello_world.py` demonstrates both MCP-only and MCP Mesh functions
- [ ] **MUST**: `system_agent.py` provides discoverable SystemAgent service
- [ ] **MUST**: Demonstration workflow is documented and reproducible
- [ ] **MUST**: Examples follow MCP SDK standards and project patterns

**Validation Commands**:
```bash
ls samples/
cat samples/README.md
mcp-mesh-dev validate samples/hello_world.py
mcp-mesh-dev validate samples/system_agent.py
```
**Expected Result**: Complete demonstration infrastructure available

#### **AC6.2: Demonstration Workflow Validation**
- [ ] **MUST**: Single agent mode shows no dependency injection (plain MCP behavior)
- [ ] **MUST**: Multi-agent mode shows automatic dependency injection (MCP Mesh behavior)
- [ ] **MUST**: Real-time service discovery demonstrated through endpoint behavior changes
- [ ] **MUST**: HTTP endpoints return correct responses for each scenario
- [ ] **MUST**: Documentation guides users through complete demonstration

**Complete Demonstration Test Scenario**:
```bash
# Step 1: Start hello_world.py
mcp-mesh-dev start samples/hello_world.py

# Step 2: Test endpoints (no dependencies)
curl http://localhost:<port>/hello_mcp
# Expected: "Hello from MCP! (No dependency injection)"
curl http://localhost:<port>/hello_mesh  
# Expected: "Hello from MCP Mesh! (No dependencies available yet)"

# Step 3: Start system_agent.py
mcp-mesh-dev start samples/system_agent.py

# Step 4: Test endpoints (with dependencies)
curl http://localhost:<port>/hello_mcp
# Expected: "Hello from MCP! (No dependency injection)" (unchanged)
curl http://localhost:<port>/hello_mesh
# Expected: "Hello, it's June 8, 2025 at 10:30 AM here, what about you?" (injected!)

# Step 5: Stop system_agent.py
mcp-mesh-dev stop system_agent.py

# Step 6: Test endpoints (dependencies removed)
curl http://localhost:<port>/hello_mesh
# Expected: "Hello from MCP Mesh! (No dependencies available yet)" (back to original)
```

**Expected Result**: Perfect demonstration of MCP vs MCP Mesh automatic dependency injection

#### **AC6.3: Demonstration Educational Value**
- [ ] **MUST**: Demonstration clearly shows interface-optional dependency injection
- [ ] **MUST**: Real-time parameter injection visible through HTTP endpoint behavior
- [ ] **MUST**: New users can understand and run demonstration in < 5 minutes
- [ ] **MUST**: Demonstration showcases all key MCP Mesh features
- [ ] **MUST**: Before/after comparison provides clear value proposition

**Validation Method**: New user testing with demonstration workflow
**Expected Result**: Clear understanding of MCP Mesh capabilities vs plain MCP

### ✅ **AC7: Architecture and Integration Validation**

#### **AC7.1: Mesh Feature Preservation**
- [ ] **MUST**: All core mesh features work through dev tools
- [ ] **MUST**: Auto-enhancement system functions correctly
- [ ] **MUST**: Registry integration is seamless
- [ ] **MUST**: Service discovery works reliably
- [ ] **MUST**: No breaking changes to existing APIs

**Validation Method**: Comprehensive testing of all mesh features via CLI
**Expected Result**: Complete mesh functionality accessible through CLI

#### **AC7.2: Performance Requirements**
- [ ] **MUST**: Service startup time < 5 seconds
- [ ] **MUST**: Agent registration time < 2 seconds
- [ ] **MUST**: CLI command response time < 1 second
- [ ] **MUST**: Status query response time < 500ms
- [ ] **MUST**: Memory usage reasonable for development workloads

**Validation Method**: Performance testing with timing measurements
**Expected Result**: All performance requirements met

#### **AC7.3: Cross-platform Compatibility**
- [ ] **MUST**: Works on Linux development environments
- [ ] **SHOULD**: Works on macOS development environments
- [ ] **SHOULD**: Works on Windows development environments
- [ ] **MUST**: Process management handles platform differences

**Validation Method**: Testing on multiple platforms
**Expected Result**: Reliable operation across platforms

### ✅ **AC8: Original Design Vision Complete Validation**

#### **AC8.1: End-to-End Workflow Validation**
**Test Scenario**: Complete original design vision workflow

```bash
# Step 1: Start registry
mcp-mesh-dev start
# Verify: Registry running, SQLite database created

# Step 2: Start intent agent
mcp-mesh-dev start intent_agent.py
# Verify: Intent agent running, registered with registry, no injected parameters

# Step 3: Start developer agent  
mcp-mesh-dev start developer_agent.py
# Verify: Developer agent running, intent agent gains dependency parameters

# Step 4: Stop developer agent
mcp-mesh-dev stop developer_agent.py
# Verify: Developer agent stopped, intent agent loses dependency parameters

# Step 5: Clean shutdown
mcp-mesh-dev stop
# Verify: All processes cleaned up, no resource leaks
```

**Acceptance Criteria**:
- [ ] **MUST**: Complete workflow executes without errors
- [ ] **MUST**: Dependency injection occurs exactly as designed
- [ ] **MUST**: Service eviction works automatically
- [ ] **MUST**: Registry state accurately reflects all changes
- [ ] **MUST**: No manual intervention required for mesh integration

#### **AC7.2: Production Readiness Validation**
- [ ] **MUST**: CLI is suitable for MCP community development use
- [ ] **MUST**: Documentation is comprehensive and accessible
- [ ] **MUST**: Error scenarios are handled gracefully
- [ ] **MUST**: Resource cleanup is reliable and complete
- [ ] **MUST**: No security vulnerabilities in local development mode

#### **AC7.3: Future Extensibility**
- [ ] **MUST**: CLI architecture supports future enhancements
- [ ] **MUST**: Integration points are well-defined and stable
- [ ] **MUST**: Configuration system supports extension
- [ ] **MUST**: Plugin architecture foundation is established

---

## 🧪 **TESTING STRATEGY**

### **Validation Phases**:

1. **Unit Testing**: Each CLI component tested in isolation
2. **Integration Testing**: CLI components working together
3. **End-to-End Testing**: Complete original design vision workflow
4. **Performance Testing**: Response times and resource usage
5. **User Acceptance Testing**: Real MCP community developer scenarios

### **Test Data Requirements**:
- Sample agent files with various `@mesh_agent` configurations
- Intentionally broken agent files for validation testing
- Performance test scenarios with multiple agents
- Cross-platform test environments

### **Success Metrics**:
- **100% Pass Rate**: All acceptance criteria must pass
- **Zero Breaking Changes**: Existing functionality preserved
- **Performance Targets**: All timing requirements met
- **User Experience**: Positive feedback from MCP community testing

---

## 📊 **VALIDATION CHECKLIST**

### **Critical Success Criteria** (Must Pass):
- [ ] Original design vision workflow works exactly as specified
- [ ] All existing examples work without modification
- [ ] Registry and agent management work reliably
- [ ] Dependency injection occurs automatically and correctly
- [ ] Service eviction works via heartbeat mechanism

### **Important Success Criteria** (Should Pass):
- [ ] Performance requirements are met
- [ ] Error handling provides helpful guidance
- [ ] Cross-platform compatibility achieved
- [ ] Developer experience is excellent
- [ ] Documentation is comprehensive

### **Enhancement Criteria** (Nice to Have):
- [ ] Demo mode provides educational value
- [ ] Advanced debugging capabilities available
- [ ] Plugin architecture foundation established
- [ ] Integration with popular development tools

---

## 🎯 **FINAL VALIDATION**

The `mcp-mesh-dev` CLI implementation will be considered complete and successful when:

1. **✅ Original Design Vision**: Complete workflow demonstrated working exactly as designed
2. **✅ Zero Modification**: All existing examples work without any code changes
3. **✅ Community Ready**: MCP community developers can immediately adopt and use
4. **✅ Production Quality**: Reliable, performant, and well-documented
5. **✅ Future Ready**: Architecture supports planned enterprise features

**Final Acceptance**: All critical success criteria pass, with at least 90% of important criteria passing.