# Integration Test Suite

This directory contains comprehensive integration tests for MCP Mesh, implementing a complete end-to-end workflow that validates the entire system.

## Overview

The integration test suite implements the following 19-step workflow:

1. **Initial Cleanup** - Clean up all processes and database files
2. **Start Registry** - Start mcp-mesh-registry, wait 5 seconds
3. **Check Registry Logs** - Verify no critical errors in registry startup
4. **Check Registry Endpoints** - Validate all registry API endpoints
5. **Start Hello World Agent** - Start hello_world.py, wait 1 minute
6. **Check Agent Logs** - Verify successful registration and heartbeats
7. **Check Agent Registration** - Verify agent appears in registry with correct capabilities
8. **Check CLI List** - Verify mcp-mesh-dev list shows the agent
9. **Start System Agent** - Start system_agent.py, wait 1 minute
10. **Check System Agent Logs** - Verify successful registration and heartbeats
11. **Check Dependency Injection** - Verify hello world receives dependency updates
12. **Check Both Agents** - Verify both agents registered with correct capabilities
13. **Check CLI List Both** - Verify mcp-mesh-dev list shows both agents
14. **Stop System Agent** - Stop system_agent.py, wait 1 minute
15. **Check Deregistration** - Verify proper deregistration/health degradation
16. **Check Dependency Removal** - Verify hello world loses dependencies
17. **Check Health Degradation** - Verify system agent shows as degraded/offline
18. **Check CLI Health Update** - Verify mcp-mesh-dev list shows updated health
19. **Final Cleanup** - Clean up all processes and database files

## Usage

### Via Makefile (Recommended)

```bash
# Run comprehensive integration tests
make test-integration

# Run quick integration test
make test-integration-quick

# Clean test environment only
make clean-test
```

### Direct Execution

```bash
# Using the test runner script
python3 run_integration_test.py

# Using pytest directly
cd tests/integration
python3 -m pytest test_comprehensive_e2e_workflow.py -v -s

# Run individual test steps
python3 -m pytest test_comprehensive_e2e_workflow.py::TestComprehensiveE2EWorkflow::test_01_initial_cleanup -v -s
```

### Using pytest

```bash
# Run with detailed output
pytest tests/integration/test_comprehensive_e2e_workflow.py -v -s --tb=short

# Run specific test class
pytest tests/integration/test_comprehensive_e2e_workflow.py::TestComprehensiveE2EWorkflow -v

# Run with coverage
pytest tests/integration/test_comprehensive_e2e_workflow.py --cov=src --cov-report=html
```

## Test Structure

### Files

- `test_comprehensive_e2e_workflow.py` - Main test suite implementing all 19 steps
- `config.py` - Configuration settings for timeouts, paths, patterns
- `README.md` - This documentation

### Key Classes

- `ProcessManager` - Manages test processes with proper logging and cleanup
- `IntegrationTestSuite` - Main test coordinator with utilities
- `TestComprehensiveE2EWorkflow` - pytest test class with individual test methods

## Configuration

Test behavior can be configured via environment variables:

```bash
# Registry connection
export MCP_MESH_REGISTRY_HOST=localhost
export MCP_MESH_REGISTRY_PORT=8000

# Test timing (in seconds)
export REGISTRY_STARTUP_WAIT=5
export AGENT_STABILIZATION_WAIT=60
export DEGRADATION_WAIT=60
```

## Expected Duration

- **Full Test Suite**: ~8-10 minutes
- **Individual Steps**: 1-60 seconds each
- **Longest Steps**: Agent stabilization waits (60 seconds each)

## Logs and Debugging

### Test Logs

All test processes are logged to temporary files:
- Registry logs: `/tmp/mcp_mesh_test_*/registry.log`
- Hello World logs: `/tmp/mcp_mesh_test_*/hello_world.log`
- System Agent logs: `/tmp/mcp_mesh_test_*/system_agent.log`

### Debugging Failed Tests

1. **Check process logs** - Review the log files for error details
2. **Check binary paths** - Ensure `make build` completed successfully
3. **Check ports** - Ensure port 8000 is not in use by other processes
4. **Check cleanup** - Run `make clean-test` to reset environment

### Manual Cleanup

If tests fail and leave processes running:

```bash
# Kill all mcp-mesh processes
make clean-test

# Or manually
pkill -f mcp-mesh-registry
pkill -f mcp-mesh-dev
pkill -f hello_world.py
pkill -f system_agent.py
```

## Requirements

### System Requirements

- Python 3.8+
- Go 1.19+
- pytest
- requests library

### Build Requirements

Tests require compiled binaries:

```bash
make build
```

### Python Dependencies

```bash
pip install pytest requests
```

## What the Tests Validate

### Registry Functionality
- ✅ Startup and health endpoints
- ✅ Agent registration API
- ✅ Agent listing API
- ✅ Heartbeat processing
- ✅ Dependency resolution

### Agent Functionality  
- ✅ Registration with proper payload format
- ✅ Heartbeat maintenance
- ✅ Capability advertisement
- ✅ Dependency declaration
- ✅ Graceful degradation

### Dependency Injection
- ✅ Dynamic dependency resolution
- ✅ Proxy creation and updates
- ✅ Dependency removal on agent shutdown
- ✅ Tag-based dependency matching

### CLI Tools
- ✅ mcp-mesh-dev list command
- ✅ Agent status reporting
- ✅ Health status updates

### Process Management
- ✅ Clean startup and shutdown
- ✅ Proper process isolation
- ✅ Database cleanup
- ✅ Log management

## Extending the Tests

### Adding New Test Steps

1. Add new test method to `TestComprehensiveE2EWorkflow`
2. Follow naming convention: `test_XX_descriptive_name`
3. Update the step number in docstring
4. Add any new patterns to `config.py`

### Adding New Validation Patterns

Edit `config.py` and add patterns to appropriate lists:
- `REGISTRY_STARTUP_PATTERNS`
- `AGENT_REGISTRATION_PATTERNS`
- `HEARTBEAT_PATTERNS`
- etc.

### Testing New Agents

1. Add agent script to `examples/`
2. Update `config.py` with expected capabilities/dependencies
3. Add agent-specific test steps
4. Update cleanup process to include new agent

## Limitations

### Test Scope

The integration tests focus on happy path scenarios and basic error handling. They do not cover:

- Network failures and retries
- Database corruption scenarios  
- Resource exhaustion conditions
- Complex multi-agent interaction patterns
- Performance under load

### Test Environment

Tests assume:
- Clean environment with no conflicting processes
- Sufficient system resources
- Stable network connectivity
- Write permissions for temporary files

### Docker Integration

The current test suite runs on the host system. For Docker-based testing:

1. The test framework can be extended to use Docker containers
2. This would provide better isolation
3. Trade-off: increased complexity and setup requirements

## Troubleshooting

### Common Issues

**Build Failures**
```bash
make clean && make build
```

**Port Conflicts**
```bash
lsof -i :8000
# Kill conflicting process or change port
```

**Permission Errors**
```bash
# Ensure write permissions for temp directory
chmod 755 /tmp
```

**Process Cleanup Issues**
```bash
make clean-test
# Or force cleanup
pkill -9 -f mcp-mesh
```

### Getting Help

1. Check test logs in `/tmp/mcp_mesh_test_*`
2. Run individual test steps to isolate issues
3. Verify examples work manually outside of tests
4. Check that all dependencies are properly installed

## Future Enhancements

### Planned Improvements

- [ ] Docker-based test execution
- [ ] Parallel test execution  
- [ ] Performance benchmarking
- [ ] Stress testing scenarios
- [ ] Network failure simulation
- [ ] Multi-platform testing

### Test Coverage Goals

- [ ] Error injection testing
- [ ] Recovery scenario testing
- [ ] Scale testing (many agents)
- [ ] Security testing
- [ ] Compatibility testing