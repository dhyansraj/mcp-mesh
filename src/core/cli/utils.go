package cli

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"mcp-mesh/src/core/tlsutil"
)

// RegistryAgent represents an agent in the registry
type RegistryAgent struct {
	ID           string    `json:"id"`
	Name         string    `json:"name"`
	Status       string    `json:"status"`
	Capabilities []string  `json:"capabilities"`
	LastSeen     time.Time `json:"last_seen"`
	Version      string    `json:"version,omitempty"`
	Description  string    `json:"description,omitempty"`
}

// RegistryResponse represents the response from the registry agents endpoint
type RegistryResponse struct {
	Agents []RegistryAgent `json:"agents"`
	Count  int             `json:"count"`
}

// defaultCLIClient is a shared HTTP client for CLI-to-registry communication.
// Reusing a single client enables connection pooling across commands.
var defaultCLIClient *http.Client
var cliClientOnce sync.Once

// getCLIClient returns a shared HTTP client for CLI-to-registry communication.
// Uses sync.Once to create the client lazily and cache it.
// TLS is configured from MCP_MESH_TLS_* env vars (CA, CERT, KEY, SKIP_VERIFY).
func getCLIClient() *http.Client {
	cliClientOnce.Do(func() {
		tlsConfig, err := tlsutil.LoadFromEnv("MCP_MESH_TLS")
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: invalid TLS configuration: %v\n", err)
			os.Exit(1)
		}

		// When no MCP_MESH_TLS_* env vars are set, check for TLS auto CA.
		// TLS auto mode generates a local CA at ~/.mcp-mesh/tls/ca.pem.
		// Auto-detecting it lets `meshctl call` work without manual env setup.
		if tlsConfig == nil {
			if homeDir, err := os.UserHomeDir(); err == nil {
				autoCA := filepath.Join(homeDir, ".mcp-mesh", "tls", "ca.pem")
				if _, statErr := os.Stat(autoCA); statErr == nil {
					caCert, readErr := os.ReadFile(autoCA)
					if readErr != nil {
						fmt.Fprintf(os.Stderr, "Warning: TLS auto CA found at %s but unreadable: %v\n", autoCA, readErr)
					} else {
						pool := x509.NewCertPool()
						if pool.AppendCertsFromPEM(caCert) {
							tlsConfig = &tls.Config{
								RootCAs:    pool,
								MinVersion: tls.VersionTLS12,
							}
						} else {
							fmt.Fprintf(os.Stderr, "Warning: TLS auto CA at %s contains invalid PEM data\n", autoCA)
						}
					}
				}
			}
		}

		defaultCLIClient = &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig:     tlsConfig,
				MaxIdleConns:        20,
				MaxIdleConnsPerHost: 10,
				IdleConnTimeout:     90 * time.Second,
			},
		}
	})
	return defaultCLIClient
}

// newTLSSkipVerifyClient returns an HTTP client that skips TLS verification.
// Used for internal health checks (IsRegistryRunning, WaitForRegistry) where
// the registry may use a self-signed cert from TLS auto or SPIRE mode.
func newTLSSkipVerifyClient() *http.Client {
	return &http.Client{
		Timeout: 5 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}
}

// newTLSClientWithOptionalCert returns the shared CLI HTTP client.
// Client certs are loaded from env vars during initialization.
func newTLSClientWithOptionalCert() *http.Client {
	return getCLIClient()
}

// IsPortAvailable checks if a port is available for use
func IsPortAvailable(host string, port int) bool {
	address := fmt.Sprintf("%s:%d", host, port)
	conn, err := net.DialTimeout("tcp", address, 1*time.Second)
	if err != nil {
		return true // Port is available
	}
	conn.Close()
	return false // Port is in use
}

// WaitForRegistry waits for the registry to become available
func WaitForRegistry(registryURL string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	healthURL := registryURL + "/health"

	client := newTLSSkipVerifyClient()
	for time.Now().Before(deadline) {
		resp, err := client.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			resp.Body.Close()
			return nil
		}
		if resp != nil {
			resp.Body.Close()
		}
		time.Sleep(500 * time.Millisecond)
	}

	return fmt.Errorf("registry did not become available within %v", timeout)
}

// IsRegistryRunning checks if the registry is currently running
func IsRegistryRunning(registryURL string) bool {
	healthURL := registryURL + "/health"
	client := newTLSSkipVerifyClient()
	resp, err := client.Get(healthURL)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// IsUIRunning checks whether the dashboard UI server is currently responding
// at /api/ui-health. Used by maybeStartUIServer for protocol-driven reuse
// decisions (so two concurrent meshctl starts don't both try to bind the
// same UI port).
func IsUIRunning(port int) bool {
	if port == 0 {
		port = 3080
	}
	healthURL := fmt.Sprintf("http://localhost:%d/api/ui-health", port)
	client := newTLSSkipVerifyClient()
	resp, err := client.Get(healthURL)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// PythonProcessFile represents the Python CLI process file format
type PythonProcessFile struct {
	Processes     map[string]interface{} `json:"processes"`
	RegistryState interface{}            `json:"registry_state"`
	LastUpdated   string                 `json:"last_updated"`
}

// GetRunningProcesses returns information about running MCP Mesh processes
func GetRunningProcesses() ([]ProcessInfo, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}

	processFile := filepath.Join(homeDir, ".mcp-mesh", "processes.json")

	// One-time migration from legacy path (~/.mcp_mesh/ -> ~/.mcp-mesh/)
	if _, err := os.Stat(processFile); os.IsNotExist(err) {
		legacyPath := filepath.Join(homeDir, ".mcp_mesh", "processes.json")
		if _, err := os.Stat(legacyPath); err == nil {
			os.MkdirAll(filepath.Dir(processFile), 0755)
			if data, readErr := os.ReadFile(legacyPath); readErr == nil {
				if writeErr := os.WriteFile(processFile, data, 0644); writeErr == nil {
					os.Remove(legacyPath)
				}
			}
		}
	}

	data, err := os.ReadFile(processFile)
	if err != nil {
		if os.IsNotExist(err) {
			return []ProcessInfo{}, nil
		}
		return nil, err
	}

	// Try to parse as Go format first (simple array)
	var processes []ProcessInfo
	if err := json.Unmarshal(data, &processes); err == nil {
		// Filter out dead processes
		var alive []ProcessInfo
		for _, proc := range processes {
			if IsProcessAlive(proc.PID) {
				alive = append(alive, proc)
			}
		}

		// Save the filtered list back
		if len(alive) != len(processes) {
			SaveRunningProcesses(alive)
		}

		return alive, nil
	}

	// Try to parse as Python format (complex structure)
	var pythonFile PythonProcessFile
	if err := json.Unmarshal(data, &pythonFile); err == nil {
		// For now, return empty list when using Python format
		// The Python processes are managed differently and we don't want to interfere
		return []ProcessInfo{}, nil
	}

	// If both formats fail, return empty list
	return []ProcessInfo{}, nil
}

// SaveRunningProcesses saves the list of running processes
func SaveRunningProcesses(processes []ProcessInfo) error {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	mcpDir := filepath.Join(homeDir, ".mcp-mesh")
	if err := os.MkdirAll(mcpDir, 0755); err != nil {
		return err
	}

	processFile := filepath.Join(mcpDir, "processes.json")
	data, err := json.MarshalIndent(processes, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(processFile, data, 0644)
}

// AddRunningProcess adds a process to the running processes list
func AddRunningProcess(proc ProcessInfo) error {
	processes, err := GetRunningProcesses()
	if err != nil {
		return err
	}

	// Remove any existing entry with the same PID
	var filtered []ProcessInfo
	for _, p := range processes {
		if p.PID != proc.PID {
			filtered = append(filtered, p)
		}
	}

	filtered = append(filtered, proc)
	return SaveRunningProcesses(filtered)
}

// RemoveRunningProcess removes a process from the running processes list
func RemoveRunningProcess(pid int) error {
	processes, err := GetRunningProcesses()
	if err != nil {
		return err
	}

	var filtered []ProcessInfo
	for _, p := range processes {
		if p.PID != pid {
			filtered = append(filtered, p)
		}
	}

	return SaveRunningProcesses(filtered)
}

// IsProcessAlive checks if a process is still running.
//
// signal(0) returns nil for any process the kernel still has an entry for —
// including zombies that have been killed but not yet reaped by their parent.
// For meshctl's purposes a zombie is "effectively dead" (the process cannot
// do any more work and is only waiting to be reaped), so we filter them out
// via a platform-specific check. See utils_linux.go / utils_other.go.
func IsProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}

	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}

	// On Unix-like systems, we can send signal 0 to check if process exists
	if err := process.Signal(syscall.Signal(0)); err != nil {
		return false
	}
	return !isProcessZombie(pid)
}

// KillProcess attempts to gracefully kill a process
func KillProcess(pid int, timeout time.Duration) error {
	if !IsProcessAlive(pid) {
		return nil // Already dead
	}

	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}

	// Try graceful shutdown first (SIGINT for Python processes)
	if err := process.Signal(os.Interrupt); err != nil {
		// If SIGINT fails, try SIGTERM
		if err := process.Signal(syscall.SIGTERM); err != nil {
			return err
		}
	}

	// For FastAPI agents, use shorter timeout and more frequent checks
	// Most FastAPI agents terminate within 1-2 seconds
	effectiveTimeout := timeout
	if effectiveTimeout > 5*time.Second {
		effectiveTimeout = 5 * time.Second // Cap at 5 seconds for responsive agents
	}

	// Wait for graceful shutdown with more frequent checks
	deadline := time.Now().Add(effectiveTimeout)
	checkInterval := 50 * time.Millisecond // Check every 50ms instead of 100ms

	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return nil // Process terminated gracefully
		}
		time.Sleep(checkInterval)
	}

	// Force kill if graceful shutdown failed
	return process.Signal(syscall.SIGKILL)
}

// StartPythonAgent starts a Python agent process
func StartPythonAgent(agentPath string, config *CLIConfig) (*exec.Cmd, error) {
	// Check if the agent file exists
	if _, err := os.Stat(agentPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("agent file not found: %s", agentPath)
	}

	// Create the command
	cmd := exec.Command("python", agentPath)

	// Set environment variables
	cmd.Env = append(os.Environ(), config.GetEnvironmentVariables()...)

	// Set up stdio
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	return cmd, nil
}

// GetRegistryAgents retrieves the list of agents from the registry
func GetRegistryAgents(registryURL string) ([]RegistryAgent, error) {
	agentsURL := registryURL + "/agents"
	client := newTLSSkipVerifyClient()
	resp, err := client.Get(agentsURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("registry returned status %d", resp.StatusCode)
	}

	var response RegistryResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode registry response: %w", err)
	}

	return response.Agents, nil
}

// FindAvailablePort finds an available port starting from the given port
func FindAvailablePort(host string, startPort int) (int, error) {
	for port := startPort; port < startPort+100; port++ {
		if IsPortAvailable(host, port) {
			return port, nil
		}
	}
	return 0, fmt.Errorf("no available port found starting from %d", startPort)
}

// AbsolutePath converts a relative path to an absolute path
func AbsolutePath(path string) (string, error) {
	if filepath.IsAbs(path) {
		return path, nil
	}
	return filepath.Abs(path)
}

// ValidateLogLevel checks if a log level is valid
func ValidateLogLevel(level string) bool {
	validLevels := []string{"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
	for _, valid := range validLevels {
		if level == valid {
			return true
		}
	}
	return false
}

// ParsePort parses a port string and validates it
func ParsePort(portStr string) (int, error) {
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return 0, fmt.Errorf("invalid port number: %s", portStr)
	}
	if port < 1 || port > 65535 {
		return 0, fmt.Errorf("port must be between 1 and 65535, got %d", port)
	}
	return port, nil
}

// AgentMatchResult represents the result of prefix matching for agent resolution
type AgentMatchResult struct {
	Agent   *EnhancedAgent  // Matched agent (if unique)
	Matches []EnhancedAgent // All matching agents (for disambiguation)
	Error   error           // Error if no match
	IsExact bool            // True if exact match (not prefix)
}

// FormattedError returns a user-friendly error message including matching options
// if there are multiple matches. Returns nil if there's no error.
func (r *AgentMatchResult) FormattedError() error {
	if r.Error == nil {
		return nil
	}
	if len(r.Matches) > 1 {
		return fmt.Errorf("%s%s", r.Error.Error(), FormatAgentMatchOptions(r.Matches))
	}
	return r.Error
}

// ResolveAgentByPrefix finds agents matching the given name or ID prefix.
// It first checks for exact matches (Name or ID), then falls back to
// case-insensitive prefix matching.
//
// Disambiguation rules (applied to both exact and prefix phases):
//  1. Exactly one match -> return it (whether healthy or unhealthy)
//  2. Multiple matches with >=1 healthy -> filter to healthy:
//     - exactly one healthy -> return it
//     - multiple healthy -> error with disambiguation list
//  3. Multiple matches all unhealthy -> return lex-first deterministically.
//     The sweep job actively purges unhealthy agents, so by the time a user
//     reads a disambiguation error and picks one, the unhealthy candidates
//     may already be gone. Just pick deterministically and be done.
//
// Callers pass `agents` already sorted by ID (see getEnhancedAgents in
// list.go), so "lex-first" is just matches[0].
func ResolveAgentByPrefix(agents []EnhancedAgent, prefix string, healthyOnly bool) *AgentMatchResult {
	result := &AgentMatchResult{}

	// Filter agents based on health status first
	var candidateAgents []EnhancedAgent
	for _, agent := range agents {
		if healthyOnly && strings.ToLower(agent.Status) != "healthy" {
			continue
		}
		candidateAgents = append(candidateAgents, agent)
	}

	// Phase 1: collect ALL exact matches (Name or ID)
	var exactMatches []EnhancedAgent
	for _, agent := range candidateAgents {
		if agent.Name == prefix || agent.ID == prefix {
			exactMatches = append(exactMatches, agent)
		}
	}
	if len(exactMatches) > 0 {
		return pickWithHealthyPreference(result, exactMatches, prefix, true /* isExact */)
	}

	// Phase 2: case-insensitive prefix matching
	var prefixMatches []EnhancedAgent
	prefixLower := strings.ToLower(prefix)

	for _, agent := range candidateAgents {
		nameLower := strings.ToLower(agent.Name)
		idLower := strings.ToLower(agent.ID)

		if strings.HasPrefix(nameLower, prefixLower) ||
			strings.HasPrefix(idLower, prefixLower) {
			prefixMatches = append(prefixMatches, agent)
		}
	}

	if len(prefixMatches) == 0 {
		if healthyOnly {
			result.Error = fmt.Errorf("no healthy agent found matching '%s'", prefix)
		} else {
			result.Error = fmt.Errorf("no agent found matching '%s'", prefix)
		}
		return result
	}

	return pickWithHealthyPreference(result, prefixMatches, prefix, false /* isExact */)
}

// pickWithHealthyPreference applies the disambiguation rule for a set of
// matches (either exact or prefix). See ResolveAgentByPrefix doc for the
// full rule.
func pickWithHealthyPreference(result *AgentMatchResult, matches []EnhancedAgent, prefix string, isExact bool) *AgentMatchResult {
	if len(matches) == 1 {
		result.Agent = &matches[0]
		result.IsExact = isExact
		result.Matches = matches
		return result
	}

	// Multiple matches — separate healthy from unhealthy
	var healthy []EnhancedAgent
	for i := range matches {
		if strings.ToLower(matches[i].Status) == "healthy" {
			healthy = append(healthy, matches[i])
		}
	}

	if len(healthy) == 1 {
		// Exactly one healthy among the matches — auto-pick it
		result.Agent = &healthy[0]
		result.IsExact = isExact
		result.Matches = healthy
		return result
	}
	if len(healthy) > 1 {
		// Multiple healthy — must disambiguate. Note: we deliberately omit
		// unhealthy candidates from result.Matches even when they share the
		// prefix, mirroring `meshctl list` default behavior (unhealthy hidden).
		// Showing dead agents in "Did you mean..." would be confusing.
		result.Matches = healthy
		result.Error = fmt.Errorf("multiple agents match '%s'", prefix)
		return result
	}

	// Zero healthy among multiple unhealthy — pick lex-first deterministically.
	// Matches are already in the sort order callers passed in (ID-sorted from
	// getEnhancedAgents), so matches[0] is the lex-first ID.
	result.Agent = &matches[0]
	result.IsExact = isExact
	result.Matches = matches
	return result
}

// FormatAgentMatchOptions formats multiple matching agents for display to the user.
func FormatAgentMatchOptions(matches []EnhancedAgent) string {
	var sb strings.Builder
	sb.WriteString("\nMatching agents:\n")

	for _, agent := range matches {
		sb.WriteString(fmt.Sprintf("  - %s (ID: %s, Status: %s)\n",
			agent.Name, agent.ID, agent.Status))
	}

	sb.WriteString("\nPlease specify a more precise agent name or ID.")
	return sb.String()
}
