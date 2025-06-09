# MCP Mesh Go Migration Development Rules

## Core Migration Principles

### Rule 1: 100% Compatibility First - No Breaking Changes
- **API Compatibility**: Go implementation must provide identical HTTP API responses
- **CLI Compatibility**: Go CLI must accept same commands, flags, and arguments as Python version
- **Configuration Compatibility**: Same environment variables, config files, and default values
- **Behavior Compatibility**: Identical error messages, logging format, and operational behavior

### Rule 2: Performance and Efficiency - Justify the Migration
- **Measurable Improvements**: All performance claims must be backed by benchmarks
- **Resource Efficiency**: Memory usage, CPU utilization, and binary size must be optimized
- **Scalability**: Support for higher concurrent loads and better resource utilization
- **Startup Performance**: Faster CLI startup and registry initialization times

### Rule 3: Maintain Architecture Integrity - Same Design Patterns
- **Registry as Passive API Server**: Preserve pull-based, K8s-style architecture
- **Agent Independence**: Maintain graceful degradation and registry-optional operation
- **Process Management**: Same localhost development experience with docker-compose style orchestration
- **Deployment Model**: Identical K8s deployment patterns and Helm chart compatibility

## Go Implementation Guidelines

### Code Organization and Structure
- **Monorepo Integration**: Go code lives alongside Python packages in same repository
- **Clean Module Structure**: Use Go modules with clear internal package organization
- **Interface Compatibility**: Maintain exact same external APIs and protocols
- **Package Naming**: Follow Go conventions while preserving functional equivalence

### API Implementation Requirements
```go
// ✅ CORRECT - Exact API compatibility
func handleRegisterAgent(c *gin.Context) {
    var agent AgentMetadata
    if err := c.ShouldBindJSON(&agent); err != nil {
        // Same error format as Python FastAPI
        c.JSON(400, gin.H{"detail": err.Error()})
        return
    }
    
    // Same business logic as Python implementation
    registry.RegisterAgent(agent)
    
    // Identical response format
    c.JSON(200, gin.H{"status": "registered", "agent_id": agent.ID})
}

// ❌ WRONG - Different response format
func handleRegisterAgent(c *gin.Context) {
    // Don't change response format
    c.JSON(200, gin.H{"success": true}) // ❌ Python returns {"status": "registered"}
}
```

### Database Layer Requirements
```go
// ✅ CORRECT - Same schema and data types using raw SQL
type Agent struct {
    ID           string    `json:"id"`
    Name         string    `json:"name"`
    Capabilities []string  `json:"capabilities"`
    LastSeen     time.Time `json:"last_seen"`
    Metadata     JSON      `json:"metadata"`
}

// Same JSON marshaling as Python
func (a Agent) MarshalJSON() ([]byte, error) {
    // Ensure exact JSON format compatibility with Python
}
```

### CLI Implementation Requirements
```go
// ✅ CORRECT - Same command structure and flags
var startCmd = &cobra.Command{
    Use:   "start [agent.py]",
    Short: "Start MCP agent with mesh runtime", // Same help text
    Args:  cobra.MaximumNArgs(1),
    RunE: func(cmd *cobra.Command, args []string) error {
        // Same flag parsing and validation as Python
        registryOnly, _ := cmd.Flags().GetBool("registry-only")
        registryURL, _ := cmd.Flags().GetString("registry-url")
        
        // Identical behavior to Python CLI
        return startAgent(args, registryOnly, registryURL)
    },
}

func init() {
    // Same flags as Python CLI
    startCmd.Flags().Bool("registry-only", false, "Start registry only")
    startCmd.Flags().String("registry-url", "", "External registry URL")
    startCmd.Flags().Bool("connect-only", false, "Connect to external registry")
}
```

## Testing and Validation Requirements

### Compatibility Testing Strategy
- **API Testing**: All existing Python tests must pass against Go registry
- **CLI Testing**: Same command-line test suite must work with Go CLI
- **Integration Testing**: Existing Python agents must work unchanged with Go runtime
- **Performance Testing**: Benchmark against Python implementation with realistic workloads

### Test Coverage Requirements
```go
// ✅ CORRECT - Test API compatibility explicitly
func TestRegisterAgentCompatibility(t *testing.T) {
    // Use exact same test data as Python tests
    testPayload := `{
        "id": "test-agent",
        "name": "Test Agent",
        "capabilities": ["file_read", "file_write"],
        "metadata": {"version": "1.0.0"}
    }`
    
    // Verify exact same response format
    response := makeRequest("POST", "/agents/register_with_metadata", testPayload)
    
    // Must match Python response exactly
    assert.Equal(t, 200, response.StatusCode)
    assert.JSONEq(t, `{"status": "registered", "agent_id": "test-agent"}`, response.Body)
}
```

### Performance Validation Requirements
- **Benchmark Comparisons**: Direct performance comparisons with Python implementation
- **Load Testing**: Stress testing under realistic agent loads
- **Memory Profiling**: Validate memory usage improvements
- **Latency Testing**: Response time improvements for critical operations

## Build and Distribution Requirements

### Cross-Platform Build Strategy
```makefile
# Makefile - Build targets for all platforms
.PHONY: build-all

build-all:
	GOOS=linux GOARCH=amd64 go build -o bin/mcp-mesh-dev-linux-amd64 ./cmd/mcp-mesh-dev
	GOOS=darwin GOARCH=amd64 go build -o bin/mcp-mesh-dev-darwin-amd64 ./cmd/mcp-mesh-dev
	GOOS=windows GOARCH=amd64 go build -o bin/mcp-mesh-dev-windows-amd64.exe ./cmd/mcp-mesh-dev
	
	GOOS=linux GOARCH=amd64 go build -o bin/mcp-mesh-registry-linux-amd64 ./cmd/mcp-mesh-registry
	GOOS=darwin GOARCH=amd64 go build -o bin/mcp-mesh-registry-darwin-amd64 ./cmd/mcp-mesh-registry
```

### Docker and K8s Requirements
- **Image Compatibility**: Same Docker image usage patterns as Python version
- **Configuration**: Same environment variables and config file mounting
- **Networking**: Identical service discovery and port configuration
- **Health Checks**: Same health check endpoints and behavior

## Migration Process Rules

### Phased Migration Strategy
1. **Phase 1**: Go components work alongside Python (same repo, different binaries)
2. **Phase 2**: Go components pass all existing tests and benchmarks
3. **Phase 3**: Production validation with side-by-side comparison
4. **Phase 4**: Full replacement with migration documentation

### Rollback Requirements
- **Immediate Rollback**: Ability to switch back to Python runtime instantly
- **Data Compatibility**: Database schema must work with both implementations
- **Process Management**: No orphaned processes or corrupted state
- **Documentation**: Clear rollback procedures for all deployment scenarios

## Package and Dependency Management

### Go Module Requirements
```go
// go.mod - Clean dependencies with clear versioning
module github.com/company/mcp-mesh

go 1.21

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/spf13/cobra v1.7.0
    github.com/mattn/go-sqlite3 v1.14.17
)
```

### Python Package Compatibility
- **Import Paths**: Python `mcp_mesh` package unchanged and unaffected
- **Runtime Independence**: Go and Python runtimes are completely separate
- **Development Experience**: Same `pip install mcp_mesh` experience for developers
- **Example Code**: All examples continue to work with either runtime

## Quality and Maintainability Standards

### Code Quality Requirements
- **Linting**: gofmt, golint, go vet must pass with zero warnings
- **Testing**: >90% test coverage for critical paths
- **Documentation**: Comprehensive godoc comments for all public APIs
- **Error Handling**: Proper error wrapping and context preservation

### Performance Monitoring
- **Benchmarking**: Continuous performance benchmarks in CI/CD
- **Profiling**: Regular memory and CPU profiling
- **Metrics**: Prometheus metrics for production monitoring
- **Alerting**: Performance regression detection

## Validation Checklist

Before considering Go migration complete:
- [ ] All existing Python tests pass against Go implementation
- [ ] Performance benchmarks show meaningful improvements
- [ ] CLI behavior identical to Python version
- [ ] API responses byte-for-byte compatible with Python
- [ ] Docker and K8s deployment works identically
- [ ] All examples run unchanged with Go runtime
- [ ] Documentation updated with migration information
- [ ] Rollback procedures tested and validated
- [ ] Cross-platform binaries tested on all supported platforms
- [ ] Memory leak testing shows no resource leaks
- [ ] Production stress testing validates stability
- [ ] Migration tooling available for existing deployments

## Success Criteria

The Go migration is successful when:
- **Zero Breaking Changes**: All existing code works without modification
- **Measurable Performance**: 10x+ improvements in key metrics
- **Production Ready**: Stable under production loads with proper monitoring
- **Developer Experience**: Same or better development workflow
- **Deployment Compatibility**: Drop-in replacement for Python runtime
- **Future Proof**: Clean architecture for continued development

---

*These rules ensure the Go migration delivers significant performance improvements while maintaining 100% compatibility with existing MCP Mesh implementations and workflows.*