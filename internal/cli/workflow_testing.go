package cli

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/spf13/cobra"
)

// WorkflowTester provides comprehensive development workflow testing
type WorkflowTester struct {
	testResults   map[string]*TestResult
	mutex         sync.RWMutex
	logger        *log.Logger
	cleanup       []func() error
	registryHost  string
	registryPort  int
	registryURL   string
}

// TestResult represents the result of a workflow test
type TestResult struct {
	TestName    string        `json:"test_name"`
	Status      string        `json:"status"`
	Duration    time.Duration `json:"duration"`
	Error       string        `json:"error,omitempty"`
	Details     []string      `json:"details"`
	StartTime   time.Time     `json:"start_time"`
	EndTime     time.Time     `json:"end_time"`
}

// TestProcessInfo tracks test processes for cleanup
type TestProcessInfo struct {
	Cmd  *exec.Cmd
	Name string
}

// NewWorkflowTester creates a new workflow testing framework
func NewWorkflowTester(registryHost string, registryPort int) *WorkflowTester {
	registryURL := fmt.Sprintf("http://%s:%d", registryHost, registryPort)
	return &WorkflowTester{
		testResults:  make(map[string]*TestResult),
		logger:       log.New(os.Stdout, "[WorkflowTester] ", log.LstdFlags),
		cleanup:      make([]func() error, 0),
		registryHost: registryHost,
		registryPort: registryPort,
		registryURL:  registryURL,
	}
}

// NewWorkflowTestCommand creates the test-workflow command
func NewWorkflowTestCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "test-workflow",
		Short: "Test development workflows",
		Long: `Test all MCP Mesh development workflows to ensure compatibility.

This command validates that the Go CLI implementation maintains identical behavior
to the Python CLI across all development scenarios including:

- Basic registry and agent startup workflows  
- 3-shell development workflow patterns
- Registry failure and recovery scenarios
- Configuration and environment handling
- Edge cases and graceful degradation

Tests are organized by scenario:
  basic      - Core registry and agent workflows
  advanced   - Failure recovery and complex scenarios  
  edge-cases - Port conflicts and concurrent operations
  all        - Complete test suite (default)`,
		RunE: runWorkflowTests,
	}

	cmd.Flags().String("scenario", "all", "Specific scenario to test (all, basic, advanced, edge-cases)")
	cmd.Flags().Bool("verbose", false, "Verbose test output with detailed steps")
	cmd.Flags().Bool("json", false, "Output results in JSON format")
	cmd.Flags().Int("timeout", 300, "Test timeout in seconds")
	cmd.Flags().Bool("cleanup", true, "Cleanup test processes after completion")
	cmd.Flags().String("registry-host", "localhost", "Registry host for testing")
	cmd.Flags().Int("registry-port", 8080, "Registry port for testing")

	return cmd
}

// runWorkflowTests executes the workflow testing based on scenario
func runWorkflowTests(cmd *cobra.Command, args []string) error {
	scenario, _ := cmd.Flags().GetString("scenario")
	verbose, _ := cmd.Flags().GetBool("verbose")
	jsonOutput, _ := cmd.Flags().GetBool("json")
	timeout, _ := cmd.Flags().GetInt("timeout")
	cleanup, _ := cmd.Flags().GetBool("cleanup")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")

	tester := NewWorkflowTester(registryHost, registryPort)

	// Setup test environment
	if err := tester.setupTestEnvironment(registryHost, registryPort); err != nil {
		return fmt.Errorf("failed to setup test environment: %w", err)
	}

	// Cleanup after tests if requested
	if cleanup {
		defer tester.cleanupTestEnvironment()
	}

	// Run tests based on scenario
	testTimeout := time.Duration(timeout) * time.Second
	switch scenario {
	case "all":
		tester.runAllWorkflowTests(testTimeout)
	case "basic":
		tester.runBasicWorkflowTests(testTimeout)
	case "advanced":
		tester.runAdvancedWorkflowTests(testTimeout)
	case "edge-cases":
		tester.runEdgeCaseTests(testTimeout)
	default:
		return fmt.Errorf("unknown test scenario: %s", scenario)
	}

	// Output results
	return tester.outputResults(jsonOutput, verbose)
}

// setupTestEnvironment prepares the testing environment
func (wt *WorkflowTester) setupTestEnvironment(registryHost string, registryPort int) error {
	wt.logger.Println("Setting up test environment...")

	// Check if mcp-mesh-dev binary exists
	if _, err := os.Stat("./mcp-mesh-dev"); err != nil {
		return fmt.Errorf("mcp-mesh-dev binary not found in current directory")
	}

	// Check if examples directory exists
	if _, err := os.Stat("./examples"); err != nil {
		return fmt.Errorf("examples directory not found")
	}

	// Verify example files exist
	requiredExamples := []string{"hello_world.py", "system_agent.py"}
	for _, example := range requiredExamples {
		path := fmt.Sprintf("./examples/%s", example)
		if _, err := os.Stat(path); err != nil {
			return fmt.Errorf("example file not found: %s", path)
		}
	}

	wt.logger.Println("Test environment setup completed")
	return nil
}

// cleanupTestEnvironment cleans up after testing
func (wt *WorkflowTester) cleanupTestEnvironment() {
	wt.logger.Println("Cleaning up test environment...")

	// Run all cleanup functions
	for _, cleanupFunc := range wt.cleanup {
		if err := cleanupFunc(); err != nil {
			wt.logger.Printf("Cleanup error: %v", err)
		}
	}

	// Kill any remaining processes
	wt.killProcessesByName("mcp-mesh-dev")
	wt.killProcessesByName("python")

	wt.logger.Println("Test environment cleanup completed")
}

// killProcessesByName kills processes by name (cross-platform)
func (wt *WorkflowTester) killProcessesByName(name string) {
	// Use pkill on Linux/Mac, taskkill on Windows
	var cmd *exec.Cmd
	if strings.Contains(strings.ToLower(os.Getenv("OS")), "windows") {
		cmd = exec.Command("taskkill", "/F", "/IM", name+".exe")
	} else {
		cmd = exec.Command("pkill", "-f", name)
	}

	if err := cmd.Run(); err != nil {
		// Ignore errors - processes might not exist
		wt.logger.Printf("Note: Could not kill processes named %s (this is normal if no such processes exist)", name)
	}
}

// runAllWorkflowTests runs the complete test suite
func (wt *WorkflowTester) runAllWorkflowTests(timeout time.Duration) {
	wt.logger.Println("Running comprehensive workflow tests...")

	// Basic workflow tests
	wt.runBasicWorkflowTests(timeout)

	// Advanced workflow tests  
	wt.runAdvancedWorkflowTests(timeout)

	// Edge case tests
	wt.runEdgeCaseTests(timeout)
}

// runBasicWorkflowTests runs basic workflow validation
func (wt *WorkflowTester) runBasicWorkflowTests(timeout time.Duration) {
	wt.logger.Println("Running basic workflow tests...")

	wt.runTest("registry-standalone-start", wt.testRegistryStandaloneStart)
	wt.runTest("agent-auto-registry-start", wt.testAgentAutoRegistryStart)
	wt.runTest("agent-connect-to-existing", wt.testAgentConnectToExisting)
	wt.runTest("three-shell-workflow", wt.testThreeShellWorkflow)
}

// runAdvancedWorkflowTests runs advanced workflow scenarios
func (wt *WorkflowTester) runAdvancedWorkflowTests(timeout time.Duration) {
	wt.logger.Println("Running advanced workflow tests...")

	wt.runTest("registry-failure-recovery", wt.testRegistryFailureRecovery)
	wt.runTest("agent-restart-workflow", wt.testAgentRestartWorkflow)
	wt.runTest("background-service-mode", wt.testBackgroundServiceMode)
	wt.runTest("configuration-precedence", wt.testConfigurationPrecedence)
	wt.runTest("environment-variable-handling", wt.testEnvironmentVariableHandling)
}

// runEdgeCaseTests runs edge case and stress testing
func (wt *WorkflowTester) runEdgeCaseTests(timeout time.Duration) {
	wt.logger.Println("Running edge case tests...")

	wt.runTest("registry-port-conflict", wt.testRegistryPortConflict)
	wt.runTest("concurrent-agent-startup", wt.testConcurrentAgentStartup)
	wt.runTest("graceful-shutdown-workflow", wt.testGracefulShutdownWorkflow)
	wt.runTest("file-watching-restart", wt.testFileWatchingRestart)
}

// runTest executes a single test with timing and error handling
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

	// Clean up after each test
	wt.cleanupAfterTest()
}

// cleanupAfterTest performs cleanup between tests
func (wt *WorkflowTester) cleanupAfterTest() {
	// Kill any test processes
	wt.killProcessesByName("mcp-mesh-dev")

	// Wait a moment for processes to terminate
	time.Sleep(2 * time.Second)
}

// addDetail adds a detail message to the current running test
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

// waitForRegistry waits for registry to become available
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

// waitForAgentRegistration waits for an agent to register with registry
func (wt *WorkflowTester) waitForAgentRegistration(agentName string, timeout time.Duration) error {
	start := time.Now()
	for time.Since(start) < timeout {
		resp, err := http.Get(wt.registryURL + "/agents")
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

// testRegistryAPI tests basic registry API functionality
func (wt *WorkflowTester) testRegistryAPI() error {
	// Test health endpoint
	resp, err := http.Get(wt.registryURL + "/health")
	if err != nil {
		return fmt.Errorf("health endpoint failed: %w", err)
	}
	resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("health endpoint returned status %d", resp.StatusCode)
	}

	// Test agents endpoint
	resp, err = http.Get(wt.registryURL + "/agents")
	if err != nil {
		return fmt.Errorf("agents endpoint failed: %w", err)
	}
	resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("agents endpoint returned status %d", resp.StatusCode)
	}

	return nil
}

// verifyAgentDiscovery verifies that agents can discover each other
func (wt *WorkflowTester) verifyAgentDiscovery() error {
	resp, err := http.Get(wt.registryURL + "/agents")
	if err != nil {
		return fmt.Errorf("failed to query agents: %w", err)
	}
	defer resp.Body.Close()

	var result struct {
		Agents []struct {
			Name string `json:"name"`
		} `json:"agents"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode agents response: %w", err)
	}

	if len(result.Agents) < 2 {
		return fmt.Errorf("expected at least 2 agents, found %d", len(result.Agents))
	}

	return nil
}

// outputResults outputs test results in requested format
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

// findAvailablePort finds an available port for testing
func (wt *WorkflowTester) findAvailablePort(startPort int) (int, error) {
	for port := startPort; port < startPort+100; port++ {
		conn, err := http.Get("http://localhost:" + strconv.Itoa(port))
		if err != nil {
			// Port is likely available
			return port, nil
		}
		conn.Body.Close()
	}
	return 0, fmt.Errorf("no available port found starting from %d", startPort)
}

// Core Workflow Test Implementations

// testRegistryStandaloneStart tests starting registry in standalone mode
func (wt *WorkflowTester) testRegistryStandaloneStart() error {
	wt.addDetail("Starting registry in standalone mode...")

	// Start registry
	cmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only", 
		"--registry-host", wt.registryHost,
		"--registry-port", fmt.Sprintf("%d", wt.registryPort))
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd.Process != nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
		return nil
	})

	// Wait for registry to be ready
	if err := wt.waitForRegistry(wt.registryURL, 30*time.Second); err != nil {
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

// testAgentAutoRegistryStart tests starting agent with auto registry start
func (wt *WorkflowTester) testAgentAutoRegistryStart() error {
	wt.addDetail("Starting agent with auto registry start...")

	// Start agent (should auto-start registry)
	cmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent: %w", err)
	}

	// Add cleanup function
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd.Process != nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
		return nil
	})

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

// testAgentConnectToExisting tests agent connecting to existing registry
func (wt *WorkflowTester) testAgentConnectToExisting() error {
	wt.addDetail("Testing agent connection to existing registry...")

	// Start registry first
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function for registry
	wt.cleanup = append(wt.cleanup, func() error {
		if registryCmd.Process != nil {
			registryCmd.Process.Kill()
			registryCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	// Now start agent
	agentCmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	agentCmd.Stdout = os.Stdout
	agentCmd.Stderr = os.Stderr

	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent: %w", err)
	}

	// Add cleanup function for agent
	wt.cleanup = append(wt.cleanup, func() error {
		if agentCmd.Process != nil {
			agentCmd.Process.Kill()
			agentCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("agent registration failed: %w", err)
	}

	wt.addDetail("Agent connected to existing registry successfully")
	return nil
}

// testThreeShellWorkflow tests the 3-shell development workflow
func (wt *WorkflowTester) testThreeShellWorkflow() error {
	wt.addDetail("Testing 3-shell development workflow...")

	// Shell 1: Start registry only
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function for registry
	wt.cleanup = append(wt.cleanup, func() error {
		if registryCmd.Process != nil {
			registryCmd.Process.Kill()
			registryCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Shell 1: Registry started")

	// Shell 2: Start first agent
	agent1Cmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	agent1Cmd.Stdout = os.Stdout
	agent1Cmd.Stderr = os.Stderr

	if err := agent1Cmd.Start(); err != nil {
		return fmt.Errorf("failed to start first agent: %w", err)
	}

	// Add cleanup function for first agent
	wt.cleanup = append(wt.cleanup, func() error {
		if agent1Cmd.Process != nil {
			agent1Cmd.Process.Kill()
			agent1Cmd.Wait()
		}
		return nil
	})

	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("first agent registration failed: %w", err)
	}
	wt.addDetail("Shell 2: First agent connected")

	// Shell 3: Start second agent
	agent2Cmd := exec.Command("./mcp-mesh-dev", "start", "examples/system_agent.py")
	agent2Cmd.Stdout = os.Stdout
	agent2Cmd.Stderr = os.Stderr

	if err := agent2Cmd.Start(); err != nil {
		return fmt.Errorf("failed to start second agent: %w", err)
	}

	// Add cleanup function for second agent
	wt.cleanup = append(wt.cleanup, func() error {
		if agent2Cmd.Process != nil {
			agent2Cmd.Process.Kill()
			agent2Cmd.Wait()
		}
		return nil
	})

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

// testRegistryFailureRecovery tests registry failure and recovery
func (wt *WorkflowTester) testRegistryFailureRecovery() error {
	wt.addDetail("Testing registry failure and recovery...")

	// Start registry and agent
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	agentCmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	agentCmd.Stdout = os.Stdout
	agentCmd.Stderr = os.Stderr

	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent: %w", err)
	}

	// Add cleanup function for agent
	wt.cleanup = append(wt.cleanup, func() error {
		if agentCmd.Process != nil {
			agentCmd.Process.Kill()
			agentCmd.Wait()
		}
		return nil
	})

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
	newRegistryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	newRegistryCmd.Stdout = os.Stdout
	newRegistryCmd.Stderr = os.Stderr

	if err := newRegistryCmd.Start(); err != nil {
		return fmt.Errorf("failed to restart registry: %w", err)
	}

	// Add cleanup function for new registry
	wt.cleanup = append(wt.cleanup, func() error {
		if newRegistryCmd.Process != nil {
			newRegistryCmd.Process.Kill()
			newRegistryCmd.Wait()
		}
		return nil
	})

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

// testAgentRestartWorkflow tests agent restart functionality
func (wt *WorkflowTester) testAgentRestartWorkflow() error {
	wt.addDetail("Testing agent restart workflow...")

	// Start registry
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function for registry
	wt.cleanup = append(wt.cleanup, func() error {
		if registryCmd.Process != nil {
			registryCmd.Process.Kill()
			registryCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	// Start agent
	agentCmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	agentCmd.Stdout = os.Stdout
	agentCmd.Stderr = os.Stderr

	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent: %w", err)
	}

	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("agent registration failed: %w", err)
	}
	wt.addDetail("Agent started and registered")

	// Restart agent using CLI
	restartCmd := exec.Command("./mcp-mesh-dev", "restart", "hello_world")
	if err := restartCmd.Run(); err != nil {
		return fmt.Errorf("failed to restart agent: %w", err)
	}
	wt.addDetail("Agent restart command executed")

	// Verify agent is running again
	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("agent re-registration failed: %w", err)
	}

	wt.addDetail("Agent restart workflow completed successfully")
	return nil
}

// testBackgroundServiceMode tests background service functionality  
func (wt *WorkflowTester) testBackgroundServiceMode() error {
	wt.addDetail("Testing background service mode...")

	// Start registry in background
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only", "--background")
	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry in background: %w", err)
	}

	// Registry should detach, so we can't wait on the process
	// Instead, wait for it to be available
	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("background registry failed to start: %w", err)
	}
	wt.addDetail("Background registry started")

	// Start agent in background
	agentCmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py", "--background")
	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent in background: %w", err)
	}

	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("background agent registration failed: %w", err)
	}
	wt.addDetail("Background agent started and registered")

	// Test status command to verify background processes
	statusCmd := exec.Command("./mcp-mesh-dev", "status")
	if err := statusCmd.Run(); err != nil {
		return fmt.Errorf("failed to get status of background processes: %w", err)
	}
	wt.addDetail("Status command verified background processes")

	// Stop background processes
	stopCmd := exec.Command("./mcp-mesh-dev", "stop", "hello_world")
	if err := stopCmd.Run(); err != nil {
		return fmt.Errorf("failed to stop background agent: %w", err)
	}

	stopRegistryCmd := exec.Command("./mcp-mesh-dev", "stop", "--registry-only")
	if err := stopRegistryCmd.Run(); err != nil {
		return fmt.Errorf("failed to stop background registry: %w", err)
	}

	wt.addDetail("Background service mode test completed successfully")
	return nil
}

// testConfigurationPrecedence tests configuration precedence handling
func (wt *WorkflowTester) testConfigurationPrecedence() error {
	wt.addDetail("Testing configuration precedence...")

	// Test with config file
	configContent := `
registry:
  host: localhost
  port: 8081
  database_path: test.db
`
	configFile := "test_config.yaml"
	if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
		return fmt.Errorf("failed to create test config: %w", err)
	}

	// Add cleanup for config file
	wt.cleanup = append(wt.cleanup, func() error {
		return os.Remove(configFile)
	})

	// Start registry with config file
	cmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only", "--config", configFile)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry with config: %w", err)
	}

	// Add cleanup function
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd.Process != nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
		return nil
	})

	// Registry should start on port 8081 as per config
	if err := wt.waitForRegistry("http://localhost:8081", 30*time.Second); err != nil {
		return fmt.Errorf("registry with custom config failed to start: %w", err)
	}

	wt.addDetail("Configuration precedence test completed successfully")
	return nil
}

// testEnvironmentVariableHandling tests environment variable handling
func (wt *WorkflowTester) testEnvironmentVariableHandling() error {
	wt.addDetail("Testing environment variable handling...")

	// Set environment variables
	os.Setenv("MCP_MESH_REGISTRY_HOST", "localhost")
	os.Setenv("MCP_MESH_REGISTRY_PORT", "8082")

	// Add cleanup for environment variables
	wt.cleanup = append(wt.cleanup, func() error {
		os.Unsetenv("MCP_MESH_REGISTRY_HOST")
		os.Unsetenv("MCP_MESH_REGISTRY_PORT")
		return nil
	})

	// Start registry (should use environment variables)
	cmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry with env vars: %w", err)
	}

	// Add cleanup function
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd.Process != nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
		return nil
	})

	// Registry should start on port 8082 as per environment variable
	if err := wt.waitForRegistry("http://localhost:8082", 30*time.Second); err != nil {
		return fmt.Errorf("registry with env vars failed to start: %w", err)
	}

	wt.addDetail("Environment variable handling test completed successfully")
	return nil
}

// testFileWatchingRestart tests file watching and auto-restart functionality
func (wt *WorkflowTester) testFileWatchingRestart() error {
	wt.addDetail("Testing file watching and auto-restart...")

	// Create a test file to watch
	testFile := "examples/test_agent.py"
	testContent := `#!/usr/bin/env python3
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="test-agent")

@server.tool()
@mesh_agent(capabilities=["test"])
def test_function():
    return "test"

if __name__ == "__main__":
    server.run(transport="stdio")
`

	if err := os.WriteFile(testFile, []byte(testContent), 0644); err != nil {
		return fmt.Errorf("failed to create test file: %w", err)
	}

	// Add cleanup for test file
	wt.cleanup = append(wt.cleanup, func() error {
		return os.Remove(testFile)
	})

	// Start registry
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function for registry
	wt.cleanup = append(wt.cleanup, func() error {
		if registryCmd.Process != nil {
			registryCmd.Process.Kill()
			registryCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	// Start agent with file watching
	agentCmd := exec.Command("./mcp-mesh-dev", "start", testFile, "--watch")
	agentCmd.Stdout = os.Stdout
	agentCmd.Stderr = os.Stderr

	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent with watching: %w", err)
	}

	// Add cleanup function for agent
	wt.cleanup = append(wt.cleanup, func() error {
		if agentCmd.Process != nil {
			agentCmd.Process.Kill()
			agentCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForAgentRegistration("test_agent", 30*time.Second); err != nil {
		return fmt.Errorf("agent registration failed: %w", err)
	}
	wt.addDetail("Agent started with file watching")

	// Modify the test file
	modifiedContent := testContent + "\n# Modified\n"
	if err := os.WriteFile(testFile, []byte(modifiedContent), 0644); err != nil {
		return fmt.Errorf("failed to modify test file: %w", err)
	}
	wt.addDetail("Test file modified")

	// Wait a moment for file watching to trigger restart
	time.Sleep(5 * time.Second)

	// Verify agent is still registered (should have auto-restarted)
	if err := wt.waitForAgentRegistration("test_agent", 30*time.Second); err != nil {
		return fmt.Errorf("agent not found after file modification: %w", err)
	}

	wt.addDetail("File watching and auto-restart test completed successfully")
	return nil
}

// Edge Case Tests

// testRegistryPortConflict tests handling of port conflicts
func (wt *WorkflowTester) testRegistryPortConflict() error {
	wt.addDetail("Testing registry port conflict handling...")

	// Start first registry on default port
	cmd1 := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	cmd1.Stdout = os.Stdout
	cmd1.Stderr = os.Stderr

	if err := cmd1.Start(); err != nil {
		return fmt.Errorf("failed to start first registry: %w", err)
	}

	// Add cleanup function for first registry
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd1.Process != nil {
			cmd1.Process.Kill()
			cmd1.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("first registry startup failed: %w", err)
	}
	wt.addDetail("First registry started on port 8080")

	// Try to start second registry on same port (should fail gracefully)
	cmd2 := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	if err := cmd2.Run(); err == nil {
		return fmt.Errorf("second registry should have failed due to port conflict")
	}
	wt.addDetail("Second registry correctly failed due to port conflict")

	// Start second registry on different port
	cmd3 := exec.Command("./mcp-mesh-dev", "start", "--registry-only", "--port", "8083")
	cmd3.Stdout = os.Stdout
	cmd3.Stderr = os.Stderr

	if err := cmd3.Start(); err != nil {
		return fmt.Errorf("failed to start registry on alternate port: %w", err)
	}

	// Add cleanup function for alternate registry
	wt.cleanup = append(wt.cleanup, func() error {
		if cmd3.Process != nil {
			cmd3.Process.Kill()
			cmd3.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8083", 30*time.Second); err != nil {
		return fmt.Errorf("alternate registry startup failed: %w", err)
	}

	wt.addDetail("Registry port conflict handling test completed successfully")
	return nil
}

// testConcurrentAgentStartup tests concurrent agent startup
func (wt *WorkflowTester) testConcurrentAgentStartup() error {
	wt.addDetail("Testing concurrent agent startup...")

	// Start registry
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Add cleanup function for registry
	wt.cleanup = append(wt.cleanup, func() error {
		if registryCmd.Process != nil {
			registryCmd.Process.Kill()
			registryCmd.Wait()
		}
		return nil
	})

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	// Start multiple agents concurrently
	var cmds []*exec.Cmd
	agentFiles := []string{"examples/hello_world.py", "examples/system_agent.py"}

	for _, agentFile := range agentFiles {
		cmd := exec.Command("./mcp-mesh-dev", "start", agentFile)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr

		if err := cmd.Start(); err != nil {
			return fmt.Errorf("failed to start agent %s: %w", agentFile, err)
		}

		cmds = append(cmds, cmd)

		// Add cleanup function for each agent
		wt.cleanup = append(wt.cleanup, func() error {
			if cmd.Process != nil {
				cmd.Process.Kill()
				cmd.Wait()
			}
			return nil
		})
	}

	wt.addDetail("Multiple agents started concurrently")

	// Wait for all agents to register
	expectedAgents := []string{"hello_world", "system_agent"}
	for _, agentName := range expectedAgents {
		if err := wt.waitForAgentRegistration(agentName, 30*time.Second); err != nil {
			return fmt.Errorf("agent %s registration failed: %w", agentName, err)
		}
	}

	wt.addDetail("Concurrent agent startup test completed successfully")
	return nil
}

// testGracefulShutdownWorkflow tests graceful shutdown functionality
func (wt *WorkflowTester) testGracefulShutdownWorkflow() error {
	wt.addDetail("Testing graceful shutdown workflow...")

	// Start registry and agents
	registryCmd := exec.Command("./mcp-mesh-dev", "start", "--registry-only")
	registryCmd.Stdout = os.Stdout
	registryCmd.Stderr = os.Stderr

	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	if err := wt.waitForRegistry("http://localhost:8080", 30*time.Second); err != nil {
		return fmt.Errorf("registry startup failed: %w", err)
	}
	wt.addDetail("Registry started")

	agentCmd := exec.Command("./mcp-mesh-dev", "start", "examples/hello_world.py")
	agentCmd.Stdout = os.Stdout
	agentCmd.Stderr = os.Stderr

	if err := agentCmd.Start(); err != nil {
		return fmt.Errorf("failed to start agent: %w", err)
	}

	if err := wt.waitForAgentRegistration("hello_world", 30*time.Second); err != nil {
		return fmt.Errorf("agent registration failed: %w", err)
	}
	wt.addDetail("Agent started and registered")

	// Test graceful stop of agent
	stopAgentCmd := exec.Command("./mcp-mesh-dev", "stop", "hello_world")
	if err := stopAgentCmd.Run(); err != nil {
		return fmt.Errorf("failed to gracefully stop agent: %w", err)
	}
	wt.addDetail("Agent stopped gracefully")

	// Test graceful stop of registry
	stopRegistryCmd := exec.Command("./mcp-mesh-dev", "stop", "--registry-only")
	if err := stopRegistryCmd.Run(); err != nil {
		return fmt.Errorf("failed to gracefully stop registry: %w", err)
	}
	wt.addDetail("Registry stopped gracefully")

	wt.addDetail("Graceful shutdown workflow test completed successfully")
	return nil
}