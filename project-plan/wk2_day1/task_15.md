# Task 15: Development Workflow Testing (30 minutes)

## Overview: Critical Architecture Preservation

**⚠️ IMPORTANT**: This migration only replaces the registry service and CLI with Go. ALL Python decorator functionality must remain unchanged:

- `@mesh_agent` decorator analysis and metadata extraction (Python)
- Dependency injection and resolution (Python)
- Service discovery and proxy creation (Python)
- Auto-registration and heartbeat mechanisms (Python)

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Core decorator implementation
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry_server.py` - Current registry API

## CRITICAL PRESERVATION REQUIREMENT

**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI development workflow functionality.

**Reference Preservation**:

- Keep ALL Python CLI workflow code as reference during migration
- Test EVERY existing development workflow and scenario
- Maintain IDENTICAL behavior for all development patterns
- Preserve ALL workflow testing and validation functionality

**Implementation Validation**:

- Each Go workflow feature must pass Python CLI behavior tests
- Development patterns must work identically to Python version
- Workflow testing must match Python implementation exactly

## Objective

Implement comprehensive development workflow testing maintaining identical behavior to Python

## Reference

`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/` directory

## Detailed Implementation

### 9.1: Complete development workflow testing system

```go
// Development workflow testing framework
type WorkflowTester struct {
    testResults map[string]*TestResult
    mutex       sync.RWMutex
    logger      *log.Logger
}

type TestResult struct {
    TestName    string        `json:"test_name"`
    Status      string        `json:"status"`
    Duration    time.Duration `json:"duration"`
    Error       string        `json:"error,omitempty"`
    Details     []string      `json:"details"`
    StartTime   time.Time     `json:"start_time"`
    EndTime     time.Time     `json:"end_time"`
}

func NewWorkflowTester() *WorkflowTester {
    return &WorkflowTester{
        testResults: make(map[string]*TestResult),
        logger:      log.New(os.Stdout, "[WorkflowTester] ", log.LstdFlags),
    }
}

func NewWorkflowTestCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "test-workflow",
        Short: "Test development workflows",
        Long:  "Test all MCP Mesh development workflows to ensure compatibility",
        RunE:  runWorkflowTests,
    }

    cmd.Flags().String("scenario", "all", "Specific scenario to test (all, basic, advanced, edge-cases)")
    cmd.Flags().Bool("verbose", false, "Verbose test output")
    cmd.Flags().Bool("json", false, "Output results in JSON format")
    cmd.Flags().Int("timeout", 300, "Test timeout in seconds")
    cmd.Flags().Bool("cleanup", true, "Cleanup test processes after completion")

    return cmd
}

func runWorkflowTests(cmd *cobra.Command, args []string) error {
    scenario, _ := cmd.Flags().GetString("scenario")
    verbose, _ := cmd.Flags().GetBool("verbose")
    jsonOutput, _ := cmd.Flags().GetBool("json")
    timeout, _ := cmd.Flags().GetInt("timeout")
    cleanup, _ := cmd.Flags().GetBool("cleanup")

    tester := NewWorkflowTester()

    // Setup test environment
    if err := tester.setupTestEnvironment(); err != nil {
        return fmt.Errorf("failed to setup test environment: %w", err)
    }

    // Cleanup after tests if requested
    if cleanup {
        defer tester.cleanupTestEnvironment()
    }

    // Run tests based on scenario
    switch scenario {
    case "all":
        tester.runAllWorkflowTests(time.Duration(timeout)*time.Second)
    case "basic":
        tester.runBasicWorkflowTests(time.Duration(timeout)*time.Second)
    case "advanced":
        tester.runAdvancedWorkflowTests(time.Duration(timeout)*time.Second)
    case "edge-cases":
        tester.runEdgeCaseTests(time.Duration(timeout)*time.Second)
    default:
        return fmt.Errorf("unknown test scenario: %s", scenario)
    }

    // Output results
    return tester.outputResults(jsonOutput, verbose)
}

func (wt *WorkflowTester) runAllWorkflowTests(timeout time.Duration) {
    wt.logger.Println("Running comprehensive workflow tests...")

    // Basic workflow tests
    wt.runTest("registry-standalone-start", wt.testRegistryStandaloneStart)
    wt.runTest("agent-auto-registry-start", wt.testAgentAutoRegistryStart)
    wt.runTest("agent-connect-to-existing", wt.testAgentConnectToExisting)

    // Development workflow tests (3-shell scenario)
    wt.runTest("three-shell-workflow", wt.testThreeShellWorkflow)
    wt.runTest("registry-first-then-agents", wt.testRegistryFirstThenAgents)
    wt.runTest("agents-first-auto-registry", wt.testAgentsFirstAutoRegistry)

    // Advanced workflow tests
    wt.runTest("registry-failure-recovery", wt.testRegistryFailureRecovery)
    wt.runTest("agent-restart-workflow", wt.testAgentRestartWorkflow)
    wt.runTest("background-service-mode", wt.testBackgroundServiceMode)

    // Configuration workflow tests
    wt.runTest("configuration-precedence", wt.testConfigurationPrecedence)
    wt.runTest("environment-variable-handling", wt.testEnvironmentVariableHandling)
    wt.runTest("file-watching-restart", wt.testFileWatchingRestart)

    // Edge case tests
    wt.runTest("registry-port-conflict", wt.testRegistryPortConflict)
    wt.runTest("concurrent-agent-startup", wt.testConcurrentAgentStartup)
    wt.runTest("graceful-shutdown-workflow", wt.testGracefulShutdownWorkflow)
}

func (wt *WorkflowTester) runTest(testName string, testFunc func() error) {
    result := &TestResult{
        TestName:  testName,
        Status:    "running",
        StartTime: time.Now(),
        Details:   []string{},
    }

    wt.mutex.Lock()
    wt.testResults[testName] = result
    wt.mutex.Unlock()

    wt.logger.Printf("Starting test: %s", testName)

    err := testFunc()

    result.EndTime = time.Now()
    result.Duration = result.EndTime.Sub(result.StartTime)

    if err != nil {
        result.Status = "failed"
        result.Error = err.Error()
        wt.logger.Printf("Test FAILED: %s - %v", testName, err)
    } else {
        result.Status = "passed"
        wt.logger.Printf("Test PASSED: %s (%.2fs)", testName, result.Duration.Seconds())
    }
}

// Core workflow tests
func (wt *WorkflowTester) testRegistryStandaloneStart() error {
    wt.addDetail("Starting registry in standalone mode...")

    // Start registry
    cmd := exec.Command("./bin/mcp-mesh-dev", "start", "--registry-only")
    if err := cmd.Start(); err != nil {
        return fmt.Errorf("failed to start registry: %w", err)
    }
    defer cmd.Process.Kill()

    // Wait for registry to be ready
    if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
        return fmt.Errorf("registry failed to start: %w", err)
    }

    wt.addDetail("Registry started successfully")

    // Test registry API
    if err := wt.testRegistryAPI(); err != nil {
        return fmt.Errorf("registry API test failed: %w", err)
    }

    wt.addDetail("Registry API working correctly")
    return nil
}

func (wt *WorkflowTester) testAgentAutoRegistryStart() error {
    wt.addDetail("Starting agent with auto registry start...")

    // Start agent (should auto-start registry)
    cmd := exec.Command("./bin/mcp-mesh-dev", "start", "examples/hello_world.py")
    if err := cmd.Start(); err != nil {
        return fmt.Errorf("failed to start agent: %w", err)
    }
    defer cmd.Process.Kill()

    // Wait for both registry and agent
    if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
        return fmt.Errorf("auto-started registry failed: %w", err)
    }

    wt.addDetail("Registry auto-started successfully")

    // Wait for agent registration
    if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
        return fmt.Errorf("agent registration failed: %w", err)
    }

    wt.addDetail("Agent registered successfully")
    return nil
}

func (wt *WorkflowTester) testThreeShellWorkflow() error {
    wt.addDetail("Testing 3-shell development workflow...")

    // Shell 1: Start registry only
    registryCmd := exec.Command("./bin/mcp-mesh-dev", "start", "--registry-only")
    if err := registryCmd.Start(); err != nil {
        return fmt.Errorf("failed to start registry: %w", err)
    }
    defer registryCmd.Process.Kill()

    if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
        return fmt.Errorf("registry startup failed: %w", err)
    }
    wt.addDetail("Shell 1: Registry started")

    // Shell 2: Start first agent
    agent1Cmd := exec.Command("./bin/mcp-mesh-dev", "start", "examples/hello_world.py")
    if err := agent1Cmd.Start(); err != nil {
        return fmt.Errorf("failed to start first agent: %w", err)
    }
    defer agent1Cmd.Process.Kill()

    if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
        return fmt.Errorf("first agent registration failed: %w", err)
    }
    wt.addDetail("Shell 2: First agent connected")

    // Shell 3: Start second agent
    agent2Cmd := exec.Command("./bin/mcp-mesh-dev", "start", "examples/system_agent.py")
    if err := agent2Cmd.Start(); err != nil {
        return fmt.Errorf("failed to start second agent: %w", err)
    }
    defer agent2Cmd.Process.Kill()

    if err := wt.waitForAgentRegistration("system_agent", 30*time.Second); err != nil {
        return fmt.Errorf("second agent registration failed: %w", err)
    }
    wt.addDetail("Shell 3: Second agent connected")

    // Verify both agents are discoverable
    if err := wt.verifyAgentDiscovery(); err != nil {
        return fmt.Errorf("agent discovery failed: %w", err)
    }

    wt.addDetail("3-shell workflow completed successfully")
    return nil
}

func (wt *WorkflowTester) testRegistryFailureRecovery() error {
    wt.addDetail("Testing registry failure and recovery...")

    // Start registry and agent
    registryCmd := exec.Command("./bin/mcp-mesh-dev", "start", "--registry-only")
    if err := registryCmd.Start(); err != nil {
        return fmt.Errorf("failed to start registry: %w", err)
    }

    if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
        return fmt.Errorf("registry startup failed: %w", err)
    }
    wt.addDetail("Registry started")

    agentCmd := exec.Command("./bin/mcp-mesh-dev", "start", "examples/hello_world.py")
    if err := agentCmd.Start(); err != nil {
        return fmt.Errorf("failed to start agent: %w", err)
    }
    defer agentCmd.Process.Kill()

    if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
        return fmt.Errorf("agent registration failed: %w", err)
    }
    wt.addDetail("Agent connected to registry")

    // Kill registry
    registryCmd.Process.Kill()
    registryCmd.Wait()
    wt.addDetail("Registry killed")

    // Verify agent continues functioning (graceful degradation)
    time.Sleep(5 * time.Second)
    wt.addDetail("Agent should continue functioning without registry")

    // Restart registry
    newRegistryCmd := exec.Command("./bin/mcp-mesh-dev", "start", "--registry-only")
    if err := newRegistryCmd.Start(); err != nil {
        return fmt.Errorf("failed to restart registry: %w", err)
    }
    defer newRegistryCmd.Process.Kill()

    if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
        return fmt.Errorf("registry restart failed: %w", err)
    }
    wt.addDetail("Registry restarted")

    // Verify agent reconnects
    if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
        return fmt.Errorf("agent reconnection failed: %w", err)
    }

    wt.addDetail("Agent reconnected successfully")
    return nil
}

// Helper methods
func (wt *WorkflowTester) addDetail(detail string) {
    wt.mutex.Lock()
    defer wt.mutex.Unlock()

    // Find the current running test
    for _, result := range wt.testResults {
        if result.Status == "running" {
            result.Details = append(result.Details, detail)
            break
        }
    }
}

func (wt *WorkflowTester) waitForRegistry(url string, timeout time.Duration) error {
    start := time.Now()
    for time.Since(start) < timeout {
        resp, err := http.Get(url + "/health")
        if err == nil {
            resp.Body.Close()
            if resp.StatusCode == 200 {
                return nil
            }
        }
        time.Sleep(1 * time.Second)
    }
    return fmt.Errorf("registry not ready after %v", timeout)
}

func (wt *WorkflowTester) waitForAgentRegistration(agentName string, timeout time.Duration) error {
    start := time.Now()
    for time.Since(start) < timeout {
        resp, err := http.Get("http://localhost:8080/agents")
        if err == nil {
            var result struct {
                Agents []struct {
                    Name string `json:"name"`
                } `json:"agents"`
            }
            json.NewDecoder(resp.Body).Decode(&result)
            resp.Body.Close()

            for _, agent := range result.Agents {
                if agent.Name == agentName {
                    return nil
                }
            }
        }
        time.Sleep(1 * time.Second)
    }
    return fmt.Errorf("agent %s not registered after %v", agentName, timeout)
}

func (wt *WorkflowTester) outputResults(jsonOutput, verbose bool) error {
    if jsonOutput {
        data, err := json.MarshalIndent(wt.testResults, "", "  ")
        if err != nil {
            return err
        }
        fmt.Println(string(data))
        return nil
    }

    // Text output
    fmt.Println("\nWorkflow Test Results:")
    fmt.Println(strings.Repeat("=", 60))

    passed := 0
    failed := 0

    for _, result := range wt.testResults {
        status := "PASS"
        if result.Status == "failed" {
            status = "FAIL"
            failed++
        } else {
            passed++
        }

        fmt.Printf("%-30s %s (%.2fs)\n", result.TestName, status, result.Duration.Seconds())

        if verbose && len(result.Details) > 0 {
            for _, detail := range result.Details {
                fmt.Printf("  - %s\n", detail)
            }
        }

        if result.Error != "" {
            fmt.Printf("  Error: %s\n", result.Error)
        }
    }

    fmt.Printf("\nSummary: %d passed, %d failed\n", passed, failed)

    if failed > 0 {
        return fmt.Errorf("workflow tests failed")
    }

    return nil
}
```

## Success Criteria

- [ ] **CRITICAL**: Complete development workflow testing system matching Python CLI exactly
- [ ] **CRITICAL**: All workflow scenarios work identically to Python version
- [ ] **CRITICAL**: 3-shell development workflow preserved with same behavior
- [ ] **CRITICAL**: Registry failure recovery works identically to Python implementation
- [ ] **CRITICAL**: Test framework matches Python CLI testing capabilities
- [ ] **CRITICAL**: All edge cases and advanced workflows function correctly
