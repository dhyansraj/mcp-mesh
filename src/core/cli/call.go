package cli

import (
	"bytes"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// MCPRequest represents an MCP JSON-RPC request
type MCPRequest struct {
	JSONRPC string                 `json:"jsonrpc"`
	ID      int                    `json:"id"`
	Method  string                 `json:"method"`
	Params  map[string]interface{} `json:"params"`
}

// MCPResponse represents an MCP JSON-RPC response
type MCPResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      int             `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *MCPError       `json:"error,omitempty"`
}

// MCPError represents an MCP JSON-RPC error
type MCPError struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// MCPCallResult holds the result and trace information from an MCP call
type MCPCallResult struct {
	Result  json.RawMessage
	TraceID string // X-Trace-Id header
	SpanID  string // X-Span-Id header
}

// TraceContext holds trace IDs for distributed tracing
type TraceContext struct {
	TraceID string
	SpanID  string
}

// generateTraceID generates a 16-byte hex trace ID (matching Python's format)
func generateTraceID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		// Fallback to time-based ID if crypto/rand fails (extremely rare)
		return fmt.Sprintf("%016x%016x", time.Now().UnixNano(), time.Now().UnixNano()^0xDEADBEEF)
	}
	return hex.EncodeToString(b)
}

// generateSpanID generates an 8-byte hex span ID (matching Python's format)
func generateSpanID() string {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		// Fallback to time-based ID if crypto/rand fails (extremely rare)
		return fmt.Sprintf("%016x", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}

// newTraceContext creates a new trace context for distributed tracing
func newTraceContext() *TraceContext {
	return &TraceContext{
		TraceID: generateTraceID(),
		SpanID:  generateSpanID(),
	}
}

// NewCallCommand creates the call command
func NewCallCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "call [agent-ID:]tool_name [arguments]",
		Short: "Call an MCP tool on an agent",
		Long: `Call an MCP tool on a registered agent.

The command discovers the agent endpoint via the registry and makes the MCP call
with proper headers. Arguments can be provided as JSON string or via --file flag.

Tool lookup matches by MCP tool name first, then falls back to capability name.
This allows calling tools by either name (e.g., 'get_weather' or 'weather.get_weather').

By default, calls are routed through the registry proxy. This allows external access
to agents running in Docker/Kubernetes without exposing individual agent ports.

Examples:
  # Most common - auto-discover agent by tool name
  meshctl call get_weather                                # Tool name only (recommended)
  meshctl call weather.get_weather                        # By capability name
  meshctl call add '{"a": 1, "b": 2}'                     # With JSON arguments
  meshctl call process --file data.json                   # Arguments from file

  # Target specific agent (use full agent ID from 'meshctl list')
  meshctl call weather-agent-7f3a2b:get_weather           # Full agent ID with UID suffix
  meshctl call calc-agent-9x8c4d:add '{"a": 1, "b": 2}'   # Agent ID from meshctl list

  # Other options
  meshctl call get_weather --registry-url http://remote:8000  # Remote registry
  meshctl call get_weather --use-proxy=false              # Call agent directly (requires direct network access)
  meshctl call get_weather --agent-url http://localhost:8080  # Direct agent call (skip registry)

Ingress mode (for Kubernetes clusters with ingress configured):
  meshctl call hello_mesh_simple --ingress-domain mcp-mesh.local                    # With DNS configured
  meshctl call hello_mesh_simple --ingress-domain mcp-mesh.local --ingress-url http://192.168.58.2  # Without DNS
  meshctl call hello_mesh_simple --ingress-domain mcp-mesh.local --ingress-url http://localhost:9080  # Port-forwarded ingress`,
		Args: cobra.RangeArgs(1, 2),
		RunE: runCallCommand,
	}

	// Registry connection flags (same as list command)
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
	cmd.Flags().Int("timeout", 30, "Request timeout in seconds")

	// Output options
	cmd.Flags().Bool("raw", false, "Output raw JSON without formatting")
	cmd.Flags().Bool("pretty", true, "Pretty print JSON output")

	// Input options
	cmd.Flags().String("file", "", "Read arguments from JSON file")

	// Direct agent connection (bypasses registry lookup for agent endpoint)
	cmd.Flags().String("agent-url", "", "Agent URL to call directly (bypasses registry endpoint lookup)")

	// Proxy mode (routes through registry, useful for external access)
	cmd.Flags().Bool("use-proxy", true, "Route calls through registry proxy (default: true, disable with --use-proxy=false)")

	// Ingress mode flags (for Kubernetes clusters with ingress)
	cmd.Flags().String("ingress-domain", "", "Ingress domain (e.g., mcp-mesh.local) - enables ingress mode")
	cmd.Flags().String("ingress-url", "", "Ingress base URL (e.g., http://192.168.58.2) - required if DNS not configured")

	// Tracing flag (Issue #310)
	cmd.Flags().Bool("trace", false, "Display trace ID for distributed tracing (use with 'meshctl trace <id>' to view call tree)")

	// Arbitrary outbound HTTP headers (Issue #1084)
	cmd.Flags().StringArrayP("header", "H", nil, "HTTP header to add to the outbound request, repeatable (format: 'Key: Value')")

	return cmd
}

func runCallCommand(cmd *cobra.Command, args []string) error {
	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Parse tool specifier (agent:tool or just tool)
	toolSpec := args[0]
	agentName, toolName := parseToolSpecifier(toolSpec)

	// Get arguments
	var toolArgs map[string]interface{}
	fileFlag, _ := cmd.Flags().GetString("file")

	if fileFlag != "" {
		// Read arguments from file
		data, err := os.ReadFile(fileFlag)
		if err != nil {
			return fmt.Errorf("failed to read arguments file: %w", err)
		}
		if err := json.Unmarshal(data, &toolArgs); err != nil {
			return fmt.Errorf("invalid JSON in arguments file: %w", err)
		}
	} else if len(args) > 1 {
		// Parse arguments from command line
		if err := json.Unmarshal([]byte(args[1]), &toolArgs); err != nil {
			return fmt.Errorf("invalid JSON arguments: %w", err)
		}
	} else {
		toolArgs = make(map[string]interface{})
	}

	// Get registry connection flags
	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	insecure, _ := cmd.Flags().GetBool("insecure")
	timeout, _ := cmd.Flags().GetInt("timeout")
	raw, _ := cmd.Flags().GetBool("raw")
	agentURL, _ := cmd.Flags().GetString("agent-url")
	ingressDomain, _ := cmd.Flags().GetString("ingress-domain")
	ingressURL, _ := cmd.Flags().GetString("ingress-url")
	useProxy, _ := cmd.Flags().GetBool("use-proxy")
	traceFlag, _ := cmd.Flags().GetBool("trace")

	// Parse and validate user-supplied headers early so we fail fast on
	// malformed input before making any network call (Issue #1084).
	headerFlags, _ := cmd.Flags().GetStringArray("header")
	userHeaders, err := parseHeaderFlags(headerFlags)
	if err != nil {
		return err
	}

	// Generate trace context if --trace flag is set (Issue #310)
	var traceCtx *TraceContext
	if traceFlag {
		traceCtx = newTraceContext()
	}

	// Create HTTP client with TLS config
	httpClient := createHTTPClient(timeout, insecure)

	// Determine agent endpoint and host header (for ingress mode)
	var agentEndpoint string
	var agentHostHeader string

	// resolvedToolName is the actual MCP tool name to use for the call.
	// It may differ from toolName when matched via capability name fallback
	// (e.g., user calls "get_weather" but MCP tool is registered as "getWeather" on Java agents).
	resolvedToolName := toolName

	if agentURL != "" {
		// Use provided agent URL directly
		agentEndpoint = agentURL
	} else if ingressDomain != "" {
		// Ingress mode: use Host headers for routing
		extractedAgentName, hostHeader, resolved, err := findAgentWithToolIngress(httpClient, ingressURL, ingressDomain, agentName, toolName)
		if err != nil {
			return fmt.Errorf("failed to find agent: %w", err)
		}
		agentHostHeader = hostHeader
		resolvedToolName = resolved
		// In ingress mode, endpoint is the ingress URL, routing done via Host header
		if ingressURL != "" {
			agentEndpoint = ingressURL
		} else {
			agentEndpoint = fmt.Sprintf("http://%s.%s", extractedAgentName, ingressDomain)
		}
	} else {
		// Direct mode: discover agent via registry
		finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)
		var resolved string
		var err error
		agentEndpoint, resolved, err = findAgentWithTool(httpClient, finalRegistryURL, agentName, toolName)
		if err != nil {
			return fmt.Errorf("failed to find agent: %w", err)
		}
		resolvedToolName = resolved

		// If using proxy mode, route through registry instead of calling agent directly
		if useProxy {
			// Extract host:port from agent endpoint
			// Format: http://hello-world-agent:8080 -> hello-world-agent:8080
			agentHostPort := strings.TrimPrefix(agentEndpoint, "http://")
			agentHostPort = strings.TrimPrefix(agentHostPort, "https://")

			// Build proxy URL: {registry}/proxy/{host:port}/mcp
			agentEndpoint = fmt.Sprintf("%s/proxy/%s", finalRegistryURL, agentHostPort)
		}
	}

	// Make MCP call using resolvedToolName (the actual MCP tool name from the registry)
	var callResult *MCPCallResult
	if ingressDomain != "" && agentURL == "" {
		// Ingress mode: need Host header
		callResult, err = callMCPToolWithHost(httpClient, agentEndpoint, agentHostHeader, resolvedToolName, toolArgs, userHeaders, traceCtx, timeout)
	} else {
		callResult, err = callMCPTool(httpClient, agentEndpoint, resolvedToolName, toolArgs, userHeaders, traceCtx, timeout)
	}
	if err != nil {
		return fmt.Errorf("MCP call failed: %w", err)
	}

	// Output result
	if raw {
		fmt.Println(string(callResult.Result))
	} else {
		var prettyJSON bytes.Buffer
		if err := json.Indent(&prettyJSON, callResult.Result, "", "  "); err != nil {
			fmt.Println(string(callResult.Result))
		} else {
			fmt.Println(prettyJSON.String())
		}
	}

	// Display trace information if --trace flag is set (Issue #310)
	// Use the trace ID we generated and injected into the request
	if traceFlag && traceCtx != nil {
		fmt.Fprintf(os.Stderr, "\nTrace ID: %s\n", traceCtx.TraceID)
		fmt.Fprintf(os.Stderr, "View trace: meshctl trace %s\n", traceCtx.TraceID)
	}

	return nil
}

// parseToolSpecifier parses "agent:tool" or "tool" format
func parseToolSpecifier(spec string) (agentName, toolName string) {
	parts := strings.SplitN(spec, ":", 2)
	if len(parts) == 2 {
		return parts[0], parts[1]
	}
	return "", parts[0]
}

// parseHeaderFlags converts repeatable "Key: Value" strings (from --header/-H,
// Issue #1084) into an http.Header. Splits on the FIRST colon; trims surrounding
// whitespace from key and value; rejects entries with no colon or an empty key.
// An empty value is allowed. Repeated same-key flags accumulate via Add.
// Returns nil, nil for empty input.
func parseHeaderFlags(raw []string) (http.Header, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	headers := http.Header{}
	for _, s := range raw {
		parts := strings.SplitN(s, ":", 2)
		if len(parts) != 2 {
			return nil, fmt.Errorf("invalid header %q: expected format 'Key: Value'", s)
		}
		key := strings.TrimSpace(parts[0])
		if key == "" {
			return nil, fmt.Errorf("invalid header %q: empty key", s)
		}
		value := strings.TrimSpace(parts[1])
		headers.Add(key, value)
	}
	return headers, nil
}

// createHTTPClient returns an HTTP client with the specified timeout.
// Uses the shared TLS config from getCLIClient but with a custom timeout.
func createHTTPClient(timeoutSeconds int, insecure bool) *http.Client {
	base := getCLIClient()
	timeout := base.Timeout
	if timeoutSeconds > 0 {
		timeout = time.Duration(timeoutSeconds) * time.Second
	}
	transport := base.Transport
	if insecure {
		transport = &http.Transport{
			TLSClientConfig:     &tls.Config{InsecureSkipVerify: true},
			MaxIdleConns:        20,
			MaxIdleConnsPerHost: 10,
			IdleConnTimeout:     90 * time.Second,
		}
	}
	if timeout != base.Timeout || transport != base.Transport {
		return &http.Client{
			Timeout:   timeout,
			Transport: transport,
		}
	}
	return base
}

// AgentWithCapabilities represents an agent from the registry with capabilities
type AgentWithCapabilities struct {
	ID           string     `json:"id"`
	Name         string     `json:"name"`
	Endpoint     string     `json:"endpoint"`
	Status       string     `json:"status"`
	Capabilities []ToolInfo `json:"capabilities"`
}

// resolveAgentPrefix resolves an agent name/prefix to a specific agent ID using prefix matching.
func resolveAgentPrefix(agents []AgentWithCapabilities, agentName string, healthyOnly bool) (string, error) {
	if agentName == "" {
		return "", nil
	}

	// Convert to EnhancedAgent format for prefix matching
	enhancedAgents := make([]EnhancedAgent, 0, len(agents))
	for _, agent := range agents {
		enhancedAgents = append(enhancedAgents, EnhancedAgent{
			ID:       agent.ID,
			Name:     agent.Name,
			Status:   agent.Status,
			Endpoint: agent.Endpoint,
		})
	}

	matchResult := ResolveAgentByPrefix(enhancedAgents, agentName, healthyOnly)
	if err := matchResult.FormattedError(); err != nil {
		return "", err
	}
	return matchResult.Agent.ID, nil
}

// findAgentWithTool queries the registry to find an agent with the specified tool.
// Returns the agent endpoint and the resolved MCP tool name (FunctionName).
// The resolved name may differ from toolName when matched via capability name fallback
// (e.g., Java agents where FunctionName is camelCase but capability Name is snake_case).
func findAgentWithTool(client *http.Client, registryURL, agentName, toolName string) (string, string, error) {
	// Get all agents from registry
	resp, err := client.Get(registryURL + "/agents")
	if err != nil {
		return "", "", fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", "", fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var agentsResp struct {
		Agents []AgentWithCapabilities `json:"agents"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&agentsResp); err != nil {
		return "", "", fmt.Errorf("failed to parse registry response: %w", err)
	}

	// Resolve agent name/prefix to specific agent ID
	targetAgentID, err := resolveAgentPrefix(agentsResp.Agents, agentName, true)
	if err != nil {
		return "", "", err
	}

	// Collect ALL healthy candidate matches (issue #956 #14) so we can error
	// with disambiguation help when multiple agents register the same tool
	// instead of silently routing to whichever sorts first.
	type callMatch struct {
		endpoint     string
		agentID      string
		agentName    string
		functionName string
	}
	var matches []callMatch

	// Pass 1: Match by function_name (MCP tool name - exact match)
	for _, agent := range agentsResp.Agents {
		if agent.Status != "healthy" {
			continue
		}
		if targetAgentID != "" && agent.ID != targetAgentID {
			continue
		}
		for _, cap := range agent.Capabilities {
			if cap.FunctionName == toolName {
				if agent.Endpoint == "" {
					return "", "", fmt.Errorf("agent '%s' has tool '%s' but no endpoint", agent.ID, toolName)
				}
				matches = append(matches, callMatch{
					endpoint:     agent.Endpoint,
					agentID:      agent.ID,
					agentName:    agent.Name,
					functionName: cap.FunctionName,
				})
				break // one match per agent is enough
			}
		}
	}

	// Pass 2: Fallback to capability name (cross-runtime consistency, e.g.
	// Java camelCase methods). Only consult this pass if Pass 1 found nothing.
	if len(matches) == 0 {
		for _, agent := range agentsResp.Agents {
			if agent.Status != "healthy" {
				continue
			}
			if targetAgentID != "" && agent.ID != targetAgentID {
				continue
			}
			for _, cap := range agent.Capabilities {
				if cap.Name == toolName {
					if agent.Endpoint == "" {
						return "", "", fmt.Errorf("agent '%s' has capability '%s' but no endpoint", agent.ID, toolName)
					}
					matches = append(matches, callMatch{
						endpoint:     agent.Endpoint,
						agentID:      agent.ID,
						agentName:    agent.Name,
						functionName: cap.FunctionName,
					})
					break
				}
			}
		}
	}

	if len(matches) == 0 {
		if agentName != "" {
			return "", "", fmt.Errorf("tool '%s' not found on agent '%s'", toolName, agentName)
		}
		return "", "", fmt.Errorf("no agent found with tool '%s'", toolName)
	}

	if len(matches) > 1 {
		// MeshJob helpers (__mesh_job_*) auto-register on every MeshJob-capable
		// agent and read/write the same registry-backed job state, so picking any
		// healthy match is semantically correct. This bypass is scoped to the
		// shared-state helpers ONLY — other __mesh_* synthetics (e.g. the
		// per-agent __mesh_*_deps carriers) still get the ambiguity UX (issue
		// #956 item #14) since matches[0] would route nondeterministically.
		if agentName == "" && isSharedStateJobHelper(toolName) {
			return matches[0].endpoint, matches[0].functionName, nil
		}
		rows := make([]toolCollisionRow, len(matches))
		for i, m := range matches {
			rows[i] = toolCollisionRow{
				AgentID:   m.agentID,
				AgentName: m.agentName,
				ToolName:  m.functionName,
			}
		}
		return "", "", formatToolCollisionError("call", toolName, rows)
	}

	return matches[0].endpoint, matches[0].functionName, nil
}

// findAgentWithToolIngress queries the registry via ingress to find an agent with the specified tool.
// Returns: extracted agent name (for ingress routing), host header for the agent, resolved MCP tool name, error.
// The resolved name may differ from toolName when matched via capability name fallback.
func findAgentWithToolIngress(client *http.Client, ingressURL, ingressDomain, agentName, toolName string) (string, string, string, error) {
	// Build registry URL and host header
	var registryRequestURL string
	registryHost := "registry." + ingressDomain

	if ingressURL != "" {
		registryRequestURL = strings.TrimSuffix(ingressURL, "/") + "/agents"
	} else {
		registryRequestURL = "http://" + registryHost + "/agents"
	}

	// Create request with Host header
	req, err := http.NewRequest("GET", registryRequestURL, nil)
	if err != nil {
		return "", "", "", fmt.Errorf("failed to create request: %w", err)
	}

	// Set Host header for ingress routing (only needed if using ingressURL)
	if ingressURL != "" {
		req.Host = registryHost
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", "", "", fmt.Errorf("failed to connect to registry via ingress at %s: %w", registryRequestURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", "", "", fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var agentsResp struct {
		Agents []AgentWithCapabilities `json:"agents"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&agentsResp); err != nil {
		return "", "", "", fmt.Errorf("failed to parse registry response: %w", err)
	}

	// Resolve agent name/prefix to specific agent ID
	targetAgentID, err := resolveAgentPrefix(agentsResp.Agents, agentName, true)
	if err != nil {
		return "", "", "", err
	}

	// Collect ALL healthy candidate matches (issue #956 #14) so we can error
	// with disambiguation help when multiple agents register the same tool.
	type ingressMatch struct {
		agent        AgentWithCapabilities
		functionName string
	}
	var matches []ingressMatch

	// Pass 1: Match by function_name (MCP tool name - exact match)
	for _, agent := range agentsResp.Agents {
		if agent.Status != "healthy" {
			continue
		}
		if targetAgentID != "" && agent.ID != targetAgentID {
			continue
		}
		for _, cap := range agent.Capabilities {
			if cap.FunctionName == toolName {
				matches = append(matches, ingressMatch{agent: agent, functionName: cap.FunctionName})
				break
			}
		}
	}

	// Pass 2: Fallback to capability name (only if Pass 1 found nothing).
	if len(matches) == 0 {
		for _, agent := range agentsResp.Agents {
			if agent.Status != "healthy" {
				continue
			}
			if targetAgentID != "" && agent.ID != targetAgentID {
				continue
			}
			for _, cap := range agent.Capabilities {
				if cap.Name == toolName {
					matches = append(matches, ingressMatch{agent: agent, functionName: cap.FunctionName})
					break
				}
			}
		}
	}

	if len(matches) == 0 {
		if agentName != "" {
			return "", "", "", fmt.Errorf("tool '%s' not found on agent '%s'", toolName, agentName)
		}
		return "", "", "", fmt.Errorf("no agent found with tool '%s'", toolName)
	}

	if len(matches) > 1 {
		// MeshJob helpers (__mesh_job_*) auto-register on every MeshJob-capable
		// agent and read/write the same registry-backed job state, so picking any
		// healthy match is semantically correct. Scoped to the shared-state
		// helpers ONLY — other __mesh_* synthetics (e.g. per-agent __mesh_*_deps
		// carriers) still get the ambiguity UX (issue #956 item #14).
		if agentName == "" && isSharedStateJobHelper(toolName) {
			m := matches[0]
			if m.agent.Endpoint == "" {
				return "", "", "", fmt.Errorf("agent '%s' has tool '%s' but no endpoint", m.agent.ID, m.functionName)
			}
			extractedName := extractAgentNameFromEndpoint(m.agent.Endpoint)
			agentHost := extractedName + "." + ingressDomain
			return extractedName, agentHost, m.functionName, nil
		}
		rows := make([]toolCollisionRow, len(matches))
		for i, m := range matches {
			rows[i] = toolCollisionRow{
				AgentID:   m.agent.ID,
				AgentName: m.agent.Name,
				ToolName:  m.functionName,
			}
		}
		return "", "", "", formatToolCollisionError("call", toolName, rows)
	}

	m := matches[0]
	if m.agent.Endpoint == "" {
		return "", "", "", fmt.Errorf("agent '%s' has tool '%s' but no endpoint", m.agent.ID, m.functionName)
	}
	extractedName := extractAgentNameFromEndpoint(m.agent.Endpoint)
	agentHost := extractedName + "." + ingressDomain
	return extractedName, agentHost, m.functionName, nil
}

// extractAgentNameFromEndpoint extracts the agent name from a K8s service endpoint
// Examples:
//   - "http://hello-world-mcp-mesh-agent.mcp-mesh:8080" -> "hello-world"
//   - "http://system-agent-mcp-mesh-agent.mcp-mesh:8080" -> "system-agent"
//   - "http://10.244.0.64:8080" -> "" (IP address, can't extract)
func extractAgentNameFromEndpoint(endpoint string) string {
	// Remove protocol prefix
	endpoint = strings.TrimPrefix(endpoint, "http://")
	endpoint = strings.TrimPrefix(endpoint, "https://")

	// Get host part (before port)
	host := strings.Split(endpoint, ":")[0]

	// Check if it's an IP address (skip extraction)
	if isIPAddress(host) {
		return ""
	}

	// Get service name (before namespace dot)
	serviceName := strings.Split(host, ".")[0]

	// Remove "-mcp-mesh-agent" suffix to get agent name
	agentName := strings.TrimSuffix(serviceName, "-mcp-mesh-agent")

	return agentName
}

// isIPAddress checks if the string looks like an IP address
func isIPAddress(s string) bool {
	parts := strings.Split(s, ".")
	if len(parts) != 4 {
		return false
	}
	for _, part := range parts {
		if len(part) == 0 || len(part) > 3 {
			return false
		}
		for _, c := range part {
			if c < '0' || c > '9' {
				return false
			}
		}
	}
	return true
}

// sseProxyTimeoutMarker is the terminal SSE comment frame the registry proxy
// appends when the upstream exchange is cut by the X-Mesh-Timeout budget
// mid-stream. Comment frames (":"-prefixed lines) are invisible to conforming
// SSE clients per the SSE spec, which makes this a spec-compliant in-band
// signal: meshctl uses it to report a definitive timeout instead of inferring
// one from elapsed time (#1201).
// Keep in sync with proxyTimeoutCommentMarker in src/core/registry/ent_handlers.go
// and SSE_PROXY_TIMEOUT_MARKER in src/runtime/typescript/src/proxy.ts. The
// literal is pinned by src/core/cli/call_test.go and
// src/core/registry/proxy_stream_test.go — a drift in either package breaks
// the partner's tests.
const sseProxyTimeoutMarker = ": mesh-proxy-timeout"

// extractMCPResponseJSON returns the JSON-RPC payload bytes from an /mcp
// response body, plus whether the body was SSE-shaped. Plain JSON bodies pass
// through unchanged (fromSSE=false). SSE bodies (FastMCP streamable-HTTP
// answers tools/call as text/event-stream) are scanned for the TERMINAL
// JSON-RPC response frame — the first data frame carrying a top-level
// "result" or "error" key. MCP streamable-HTTP may interleave notification
// frames (progress, logging: method+params, no result/error) on the same
// stream BEFORE the response; those must be skipped, not returned — a
// notification unmarshals "successfully" into MCPResponse with nil
// Result/Error, which would silently surface the wrong payload. Comment
// frames (lines starting with ":", e.g. sse-starlette's `: ping - <ts>`
// keepalives) are ignored per the SSE spec (#1201).
//
// An SSE stream that ends without a terminal response frame is an error,
// never a result: it means the exchange was cut (typically by the
// X-Mesh-Timeout budget at the registry proxy) before the agent answered.
// The error is timeout-shaped when the proxy's terminal marker is present or
// the elapsed wall time consumed the budget; otherwise it is reported as a
// protocol error (noting any notification frames that did arrive). A data
// frame that does not parse as JSON (cut mid-frame) is returned as-is so the
// caller's unmarshal failure routes to sseTruncatedFrameError.
//
// fromSSE tells the caller whether a downstream JSON parse failure may fall
// back to the raw body: only non-SSE bodies (legacy plain-text responses)
// qualify. An SSE body is a transport envelope — returning it verbatim would
// leak keepalive comments and the proxy's timeout marker as a "successful"
// result (see sseTruncatedFrameError).
func extractMCPResponseJSON(body []byte, contentType string, elapsed time.Duration, timeoutSeconds int) ([]byte, bool, error) {
	bodyStr := string(body)
	isSSE := strings.Contains(contentType, "text/event-stream") ||
		strings.HasPrefix(bodyStr, "event:") ||
		strings.HasPrefix(bodyStr, "data:") ||
		strings.HasPrefix(bodyStr, ":")
	if !isSSE {
		return body, false, nil
	}

	var firstUnparseable []byte
	sawNotifications := false
	for _, line := range strings.Split(bodyStr, "\n") {
		line = strings.TrimRight(line, "\r")
		if strings.HasPrefix(line, ":") {
			// SSE comment frame — never payload (SSE spec: ignore ":" lines).
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "" {
			continue
		}
		var probe map[string]json.RawMessage
		if err := json.Unmarshal([]byte(data), &probe); err == nil {
			if _, ok := probe["result"]; ok {
				return []byte(data), true, nil
			}
			if _, ok := probe["error"]; ok {
				return []byte(data), true, nil
			}
			// Valid JSON object without a terminal key — a JSON-RPC
			// notification (progress/logging). Not the response; keep scanning.
			sawNotifications = true
			continue
		}
		// Not parseable as a JSON object — likely the response frame cut
		// mid-payload. Remember the first one; only used if no complete
		// terminal frame follows.
		if firstUnparseable == nil {
			firstUnparseable = []byte(data)
		}
	}

	if firstUnparseable != nil {
		return firstUnparseable, true, nil
	}
	return nil, true, sseStreamEndedError(elapsed, timeoutSeconds, sseBodyProxyTimeoutSignaled(bodyStr), sawNotifications)
}

// sseBodyProxyTimeoutSignaled reports whether the SSE body contains the
// registry proxy's terminal timeout marker (a comment frame, so the marker
// prefix already includes the ":"). Scanned over the whole body because the
// marker is appended AFTER any partial frame the cut left behind — a
// first-frames-only scan would miss it on mid-data-frame truncation.
func sseBodyProxyTimeoutSignaled(bodyStr string) bool {
	for _, line := range strings.Split(bodyStr, "\n") {
		if strings.HasPrefix(strings.TrimRight(line, "\r"), sseProxyTimeoutMarker) {
			return true
		}
	}
	return false
}

// sseElapsedConsumedBudget reports whether the elapsed wall time consumed the
// X-Mesh-Timeout budget. For budgets above 1s a 1s slack absorbs network and
// scheduling jitter; for 1s-and-under budgets the slack would swallow the
// whole budget (any close, however fast, would classify as a timeout), so the
// comparison is against the full budget instead. Shared by the data-less
// (sseStreamEndedError) and truncated-frame (sseTruncatedFrameError) paths so
// the heuristic can't drift between them.
func sseElapsedConsumedBudget(elapsed time.Duration, timeoutSeconds int) bool {
	if timeoutSeconds <= 0 {
		return false
	}
	budget := time.Duration(timeoutSeconds) * time.Second
	threshold := budget
	if budget > time.Second {
		threshold = budget - time.Second
	}
	return elapsed >= threshold
}

// sseStreamEndedError shapes the failure for an SSE response that carried no
// terminal response frame. proxyTimeoutSignaled means the registry proxy
// explicitly marked the stream as cut by its timeout cap; without that
// signal, elapsed wall time consuming the X-Mesh-Timeout budget (see
// sseElapsedConsumedBudget) is treated as a timeout, and anything quicker as
// a protocol error (the agent or proxy closed the stream early).
// sawNotifications enriches the protocol error: the stream carried JSON-RPC
// notification frames (so the agent was alive and talking) but never the
// response.
func sseStreamEndedError(elapsed time.Duration, timeoutSeconds int, proxyTimeoutSignaled, sawNotifications bool) error {
	if proxyTimeoutSignaled || sseElapsedConsumedBudget(elapsed, timeoutSeconds) {
		return sseBudgetTimeoutError(elapsed, timeoutSeconds, "expired before the agent sent a response")
	}
	detail := ""
	if sawNotifications {
		detail = " — the stream carried notification frames but never a terminal result/error frame"
	}
	return fmt.Errorf(
		"agent closed the SSE stream after %s without sending a response%s (X-Mesh-Timeout budget: %ds)",
		elapsed.Round(100*time.Millisecond), detail, timeoutSeconds)
}

// sseTruncatedFrameError shapes the failure for an SSE data frame that was
// extracted but does not parse as JSON — the stream was cut mid-frame, so the
// payload is incomplete. Timeout-shaped when the proxy's terminal marker is
// in the body (it is appended after the partial frame) or the elapsed wall
// time consumed the budget; otherwise a protocol error. Never falls back to
// the raw body: that would report the truncated envelope (marker included) as
// a successful result with exit 0.
func sseTruncatedFrameError(bodyStr string, elapsed time.Duration, timeoutSeconds int) error {
	if sseBodyProxyTimeoutSignaled(bodyStr) || sseElapsedConsumedBudget(elapsed, timeoutSeconds) {
		return sseBudgetTimeoutError(elapsed, timeoutSeconds, "expired mid-response, cutting the result frame short")
	}
	return fmt.Errorf(
		"agent sent a truncated or invalid SSE data frame after %s — the stream closed before the JSON payload completed (X-Mesh-Timeout budget: %ds)",
		elapsed.Round(100*time.Millisecond), timeoutSeconds)
}

// sseBudgetTimeoutError renders the timeout-shaped error shared by the
// data-less and truncated-frame SSE failure modes: names the budget, what it
// cut (the `what` clause), and the --timeout remedy.
func sseBudgetTimeoutError(elapsed time.Duration, timeoutSeconds int, what string) error {
	budgetLabel := "the X-Mesh-Timeout budget"
	if timeoutSeconds > 0 {
		budgetLabel = fmt.Sprintf("the X-Mesh-Timeout budget (%ds)", timeoutSeconds)
	}
	suggested := timeoutSeconds * 2
	if suggested <= 0 {
		suggested = 120
	}
	return fmt.Errorf(
		"call timed out after %s: %s %s — retry with a larger --timeout (e.g. --timeout %d)",
		elapsed.Round(100*time.Millisecond), budgetLabel, what, suggested)
}

// callMCPToolWithHost makes an MCP tools/call request with a custom Host header (for ingress)
func callMCPToolWithHost(client *http.Client, endpoint, hostHeader, toolName string, args map[string]interface{}, userHeaders http.Header, traceCtx *TraceContext, timeout int) (*MCPCallResult, error) {
	// Inject trace context into arguments (for agents that can't access HTTP headers)
	// This is in addition to HTTP headers for maximum compatibility
	argsWithTrace := args
	if traceCtx != nil {
		argsWithTrace = make(map[string]interface{})
		for k, v := range args {
			argsWithTrace[k] = v
		}
		argsWithTrace["_trace_id"] = traceCtx.TraceID
	}

	// Build MCP request
	mcpReq := MCPRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name":      toolName,
			"arguments": argsWithTrace,
		},
	}

	reqBody, err := json.Marshal(mcpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Make request to agent's /mcp endpoint
	mcpURL := strings.TrimSuffix(endpoint, "/") + "/mcp"
	req, err := http.NewRequest("POST", mcpURL, bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// User-supplied headers (#1084) are applied first so framework-managed
	// headers below (Content-Type, Accept, X-Mesh-Timeout, X-Trace-ID, Host)
	// always win on conflict and can't be broken by user input.
	for k, vs := range userHeaders {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	// Propagate timeout to registry proxy (#656)
	if timeout > 0 {
		req.Header.Set("X-Mesh-Timeout", strconv.Itoa(timeout))
	}

	// Inject trace headers if tracing is enabled (Issue #310)
	if traceCtx != nil {
		req.Header.Set("X-Trace-ID", traceCtx.TraceID)
	}

	// Set Host header for ingress routing
	if hostHeader != "" {
		req.Host = hostHeader
	}

	start := time.Now()
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to call agent at %s (Host: %s): %w", mcpURL, hostHeader, err)
	}
	defer resp.Body.Close()

	// Use injected trace IDs (we know them upfront)
	traceID := ""
	spanID := ""
	if traceCtx != nil {
		traceID = traceCtx.TraceID
		spanID = traceCtx.SpanID
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(body))
	}

	// Extract the JSON payload, SSE-aware (#1201): comment frames are skipped
	// and a data-less SSE stream surfaces as a timeout/protocol error instead
	// of leaking keepalive text as the "result".
	jsonData, fromSSE, err := extractMCPResponseJSON(body, resp.Header.Get("Content-Type"), time.Since(start), timeout)
	if err != nil {
		return nil, err
	}

	// Parse MCP response
	var mcpResp MCPResponse
	if err := json.Unmarshal(jsonData, &mcpResp); err != nil {
		if fromSSE {
			// The extracted SSE data frame is not valid JSON — the stream was
			// cut mid-frame. Never fall back to the raw body here: it is a
			// transport envelope (keepalives, the proxy's timeout marker, the
			// partial frame) and returning it would report garbage as success.
			return nil, sseTruncatedFrameError(string(body), time.Since(start), timeout)
		}
		// Return raw body if not valid JSON-RPC (legacy plain-text responses)
		return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
	}

	if mcpResp.Error != nil {
		return nil, formatMCPError(mcpResp.Error)
	}

	if mcpResp.Result != nil {
		return &MCPCallResult{Result: mcpResp.Result, TraceID: traceID, SpanID: spanID}, nil
	}

	return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
}

// callMCPTool makes an MCP tools/call request to the agent
func callMCPTool(client *http.Client, endpoint, toolName string, args map[string]interface{}, userHeaders http.Header, traceCtx *TraceContext, timeout int) (*MCPCallResult, error) {
	// Inject trace context into arguments (for agents that can't access HTTP headers)
	// This is in addition to HTTP headers for maximum compatibility
	argsWithTrace := args
	if traceCtx != nil {
		argsWithTrace = make(map[string]interface{})
		for k, v := range args {
			argsWithTrace[k] = v
		}
		argsWithTrace["_trace_id"] = traceCtx.TraceID
	}

	// Build MCP request
	mcpReq := MCPRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name":      toolName,
			"arguments": argsWithTrace,
		},
	}

	reqBody, err := json.Marshal(mcpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Make request to agent's /mcp endpoint
	mcpURL := strings.TrimSuffix(endpoint, "/") + "/mcp"
	req, err := http.NewRequest("POST", mcpURL, bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// User-supplied headers (#1084) are applied first so framework-managed
	// headers below (Content-Type, Accept, X-Mesh-Timeout, X-Trace-ID, Host)
	// always win on conflict and can't be broken by user input.
	for k, vs := range userHeaders {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	// Propagate timeout to registry proxy (#656)
	if timeout > 0 {
		req.Header.Set("X-Mesh-Timeout", strconv.Itoa(timeout))
	}

	// Inject trace headers if tracing is enabled (Issue #310)
	if traceCtx != nil {
		req.Header.Set("X-Trace-ID", traceCtx.TraceID)
	}

	start := time.Now()
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to call agent at %s: %w\n\n"+
			"Hint: If you're running meshctl from outside Docker/Kubernetes and proxy mode\n"+
			"is disabled, the agent hostname may not be reachable from your network.\n\n"+
			"Options:\n"+
			"  - Use proxy mode (default): meshctl call <tool_name>\n"+
			"  - Use direct agent URL: meshctl call <tool_name> --use-proxy=false --agent-url http://localhost:<exposed_port>", mcpURL, err)
	}
	defer resp.Body.Close()

	// Use injected trace IDs (we know them upfront)
	traceID := ""
	spanID := ""
	if traceCtx != nil {
		traceID = traceCtx.TraceID
		spanID = traceCtx.SpanID
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("agent returned status %d: %s", resp.StatusCode, string(body))
	}

	// Extract the JSON payload, SSE-aware (#1201): comment frames are skipped
	// and a data-less SSE stream surfaces as a timeout/protocol error instead
	// of leaking keepalive text as the "result".
	jsonData, fromSSE, err := extractMCPResponseJSON(body, resp.Header.Get("Content-Type"), time.Since(start), timeout)
	if err != nil {
		return nil, err
	}

	// Parse MCP response
	var mcpResp MCPResponse
	if err := json.Unmarshal(jsonData, &mcpResp); err != nil {
		if fromSSE {
			// The extracted SSE data frame is not valid JSON — the stream was
			// cut mid-frame. Never fall back to the raw body here: it is a
			// transport envelope (keepalives, the proxy's timeout marker, the
			// partial frame) and returning it would report garbage as success.
			return nil, sseTruncatedFrameError(string(body), time.Since(start), timeout)
		}
		// Return raw body if not valid JSON-RPC (legacy plain-text responses)
		return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
	}

	if mcpResp.Error != nil {
		return nil, formatMCPError(mcpResp.Error)
	}

	if mcpResp.Result != nil {
		return &MCPCallResult{Result: mcpResp.Result, TraceID: traceID, SpanID: spanID}, nil
	}

	return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
}

// formatMCPError renders an MCP JSON-RPC error as a single clean line for
// the user. It is the canonical error formatter for tools/call replies and
// handles two failure modes observed in v2.0.0-beta.1 smoke (issue #956
// items #10 + #11):
//
//  1. Pydantic validation errors arrive in Error.Data as either a list of
//     validation issues or a stringified error containing
//     "https://errors.pydantic.dev/..." links. Those URLs are noise to the
//     CLI user; strip them and keep the human-readable message only.
//
//  2. Some agents echo the same string in Error.Message AND inside
//     Error.Data (e.g., {"message": "..."}). Render it once. If Data
//     adds genuinely-new information, include it after a single space.
func formatMCPError(e *MCPError) error {
	if e == nil {
		return fmt.Errorf("MCP error: unknown")
	}

	msg := strings.TrimSpace(e.Message)
	dataStr := stripPydanticDevURLs(extractMCPErrorData(e.Data))
	dataStr = strings.TrimSpace(dataStr)

	if dataStr == "" || dataStr == msg {
		return fmt.Errorf("%s", msg)
	}
	// Data adds info beyond the message — append once, no duplication.
	return fmt.Errorf("%s: %s", msg, dataStr)
}

// extractMCPErrorData reduces an MCPError.Data payload to a single
// human-readable string. Handles the common shapes:
//   - nil -> ""
//   - string -> the string itself
//   - map with "message" / "msg" / "detail" -> that field
//   - map with "errors" or list payload -> joined messages
//   - anything else -> JSON serialization (no Go-style %v output)
func extractMCPErrorData(data interface{}) string {
	if data == nil {
		return ""
	}
	switch v := data.(type) {
	case string:
		return v
	case map[string]interface{}:
		// Pydantic-shaped or plain {"message": "..."} envelope.
		for _, key := range []string{"message", "msg", "detail", "error"} {
			if s, ok := v[key].(string); ok && s != "" {
				return s
			}
		}
		// Nested validation list under "errors" or "detail".
		for _, key := range []string{"errors", "detail"} {
			if lst, ok := v[key].([]interface{}); ok {
				return joinValidationMessages(lst)
			}
		}
	case []interface{}:
		return joinValidationMessages(v)
	}
	// Fallback: JSON for anything we don't recognize.
	if b, err := json.Marshal(data); err == nil {
		return string(b)
	}
	return ""
}

// joinValidationMessages flattens a Pydantic-style validation list into a
// single human line, using each entry's "msg" / "message" / "loc" hints.
func joinValidationMessages(items []interface{}) string {
	parts := make([]string, 0, len(items))
	for _, it := range items {
		m, ok := it.(map[string]interface{})
		if !ok {
			continue
		}
		var msg string
		for _, key := range []string{"msg", "message", "detail"} {
			if s, ok := m[key].(string); ok && s != "" {
				msg = s
				break
			}
		}
		if msg == "" {
			continue
		}
		if loc, ok := m["loc"].([]interface{}); ok && len(loc) > 0 {
			parts = append(parts, fmt.Sprintf("%v: %s", loc, msg))
		} else {
			parts = append(parts, msg)
		}
	}
	return strings.Join(parts, "; ")
}

// stripPydanticDevURLs removes "For further information visit
// https://errors.pydantic.dev/..." trailers that Pydantic appends to
// validation errors. They're noise in CLI output (issue #956 #10).
func stripPydanticDevURLs(s string) string {
	if !strings.Contains(s, "pydantic.dev") {
		return s
	}
	lines := strings.Split(s, "\n")
	keep := lines[:0]
	for _, line := range lines {
		t := strings.TrimSpace(line)
		if strings.HasPrefix(t, "For further information visit") && strings.Contains(t, "pydantic.dev") {
			continue
		}
		// Strip inline "https://errors.pydantic.dev/..." substrings.
		for {
			idx := strings.Index(line, "https://errors.pydantic.dev")
			if idx < 0 {
				break
			}
			end := idx
			for end < len(line) && line[end] != ' ' && line[end] != '\n' && line[end] != '"' {
				end++
			}
			line = line[:idx] + line[end:]
		}
		keep = append(keep, strings.TrimRight(line, " "))
	}
	return strings.TrimSpace(strings.Join(keep, "\n"))
}
