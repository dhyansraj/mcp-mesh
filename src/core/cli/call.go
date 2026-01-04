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
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// MCPCallResult holds the result and trace information from an MCP call
type MCPCallResult struct {
	Result   json.RawMessage
	TraceID  string // X-Trace-Id header
	SpanID   string // X-Span-Id header
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

By default, calls are routed through the registry proxy. This allows external access
to agents running in Docker/Kubernetes without exposing individual agent ports.

Examples:
  # Most common - auto-discover agent by tool name
  meshctl call get_weather                                # Tool name only (recommended)
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

	if agentURL != "" {
		// Use provided agent URL directly
		agentEndpoint = agentURL
	} else if ingressDomain != "" {
		// Ingress mode: use Host headers for routing
		extractedAgentName, hostHeader, err := findAgentWithToolIngress(httpClient, ingressURL, ingressDomain, agentName, toolName)
		if err != nil {
			return fmt.Errorf("failed to find agent: %w", err)
		}
		agentHostHeader = hostHeader
		// In ingress mode, endpoint is the ingress URL, routing done via Host header
		if ingressURL != "" {
			agentEndpoint = ingressURL
		} else {
			agentEndpoint = fmt.Sprintf("http://%s.%s", extractedAgentName, ingressDomain)
		}
	} else {
		// Direct mode: discover agent via registry
		finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)
		var err error
		agentEndpoint, err = findAgentWithTool(httpClient, finalRegistryURL, agentName, toolName)
		if err != nil {
			return fmt.Errorf("failed to find agent: %w", err)
		}

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

	// Make MCP call
	var callResult *MCPCallResult
	if ingressDomain != "" && agentURL == "" {
		// Ingress mode: need Host header
		callResult, err = callMCPToolWithHost(httpClient, agentEndpoint, agentHostHeader, toolName, toolArgs, traceCtx)
	} else {
		callResult, err = callMCPTool(httpClient, agentEndpoint, toolName, toolArgs, traceCtx)
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

// createHTTPClient creates an HTTP client with optional TLS skip
func createHTTPClient(timeoutSeconds int, insecure bool) *http.Client {
	transport := &http.Transport{}

	if insecure {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	return &http.Client{
		Timeout:   time.Duration(timeoutSeconds) * time.Second,
		Transport: transport,
	}
}

// AgentWithCapabilities represents an agent from the registry with capabilities
type AgentWithCapabilities struct {
	ID           string     `json:"id"`
	Name         string     `json:"name"`
	Endpoint     string     `json:"endpoint"`
	Status       string     `json:"status"`
	Capabilities []ToolInfo `json:"capabilities"`
}

// findAgentWithTool queries the registry to find an agent with the specified tool
func findAgentWithTool(client *http.Client, registryURL, agentName, toolName string) (string, error) {
	// Get all agents from registry
	resp, err := client.Get(registryURL + "/agents")
	if err != nil {
		return "", fmt.Errorf("failed to connect to registry at %s: %w", registryURL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var agentsResp struct {
		Agents []AgentWithCapabilities `json:"agents"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&agentsResp); err != nil {
		return "", fmt.Errorf("failed to parse registry response: %w", err)
	}

	// Find agent with matching tool (prefer healthy agents)
	for _, agent := range agentsResp.Agents {
		// Skip unhealthy agents
		if agent.Status != "healthy" {
			continue
		}

		// If agent name is specified, filter by it
		if agentName != "" && agent.Name != agentName && agent.ID != agentName {
			continue
		}

		// Check if agent has the tool (function_name is the MCP tool name)
		for _, cap := range agent.Capabilities {
			if cap.FunctionName == toolName {
				if agent.Endpoint == "" {
					return "", fmt.Errorf("agent '%s' has tool '%s' but no endpoint", agent.Name, toolName)
				}
				return agent.Endpoint, nil
			}
		}
	}

	if agentName != "" {
		return "", fmt.Errorf("tool '%s' not found on agent '%s'", toolName, agentName)
	}
	return "", fmt.Errorf("no agent found with tool '%s'", toolName)
}

// findAgentWithToolIngress queries the registry via ingress to find an agent with the specified tool
// Returns: extracted agent name (for ingress routing), host header for the agent, error
func findAgentWithToolIngress(client *http.Client, ingressURL, ingressDomain, agentName, toolName string) (string, string, error) {
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
		return "", "", fmt.Errorf("failed to create request: %w", err)
	}

	// Set Host header for ingress routing (only needed if using ingressURL)
	if ingressURL != "" {
		req.Host = registryHost
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("failed to connect to registry via ingress at %s: %w", registryRequestURL, err)
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

	// Find agent with matching tool (prefer healthy agents)
	for _, agent := range agentsResp.Agents {
		// Skip unhealthy agents
		if agent.Status != "healthy" {
			continue
		}

		// If agent name is specified, filter by it
		if agentName != "" && agent.Name != agentName && agent.ID != agentName {
			continue
		}

		// Check if agent has the tool (function_name is the MCP tool name)
		for _, cap := range agent.Capabilities {
			if cap.FunctionName == toolName {
				if agent.Endpoint == "" {
					return "", "", fmt.Errorf("agent '%s' has tool '%s' but no endpoint", agent.Name, toolName)
				}
				// Extract agent name from endpoint for ingress routing
				// Pattern: {agent-name}-mcp-mesh-agent.{namespace}:{port} -> {agent-name}
				extractedName := extractAgentNameFromEndpoint(agent.Endpoint)
				agentHost := extractedName + "." + ingressDomain
				return extractedName, agentHost, nil
			}
		}
	}

	if agentName != "" {
		return "", "", fmt.Errorf("tool '%s' not found on agent '%s'", toolName, agentName)
	}
	return "", "", fmt.Errorf("no agent found with tool '%s'", toolName)
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

// callMCPToolWithHost makes an MCP tools/call request with a custom Host header (for ingress)
func callMCPToolWithHost(client *http.Client, endpoint, hostHeader, toolName string, args map[string]interface{}, traceCtx *TraceContext) (*MCPCallResult, error) {
	// Build MCP request
	mcpReq := MCPRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name":      toolName,
			"arguments": args,
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

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	// Inject trace headers if tracing is enabled (Issue #310)
	if traceCtx != nil {
		req.Header.Set("X-Trace-ID", traceCtx.TraceID)
		req.Header.Set("X-Parent-Span", traceCtx.SpanID)
	}

	// Set Host header for ingress routing
	if hostHeader != "" {
		req.Host = hostHeader
	}

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

	// Check if response is SSE format and extract JSON data
	bodyStr := string(body)
	jsonData := body

	// SSE format: "event: message\ndata: {json}\n\n"
	if strings.HasPrefix(bodyStr, "event:") || strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") {
		// Extract JSON from SSE data line
		for _, line := range strings.Split(bodyStr, "\n") {
			if strings.HasPrefix(line, "data:") {
				jsonData = []byte(strings.TrimPrefix(line, "data:"))
				jsonData = []byte(strings.TrimSpace(string(jsonData)))
				break
			}
		}
	}

	// Parse MCP response
	var mcpResp MCPResponse
	if err := json.Unmarshal(jsonData, &mcpResp); err != nil {
		// Return raw body if not valid JSON-RPC
		return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
	}

	if mcpResp.Error != nil {
		return nil, fmt.Errorf("MCP error %d: %s", mcpResp.Error.Code, mcpResp.Error.Message)
	}

	if mcpResp.Result != nil {
		return &MCPCallResult{Result: mcpResp.Result, TraceID: traceID, SpanID: spanID}, nil
	}

	return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
}

// callMCPTool makes an MCP tools/call request to the agent
func callMCPTool(client *http.Client, endpoint, toolName string, args map[string]interface{}, traceCtx *TraceContext) (*MCPCallResult, error) {
	// Build MCP request
	mcpReq := MCPRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name":      toolName,
			"arguments": args,
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

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	// Inject trace headers if tracing is enabled (Issue #310)
	if traceCtx != nil {
		req.Header.Set("X-Trace-ID", traceCtx.TraceID)
		req.Header.Set("X-Parent-Span", traceCtx.SpanID)
	}

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

	// Check if response is SSE format and extract JSON data
	bodyStr := string(body)
	jsonData := body

	// SSE format: "event: message\ndata: {json}\n\n"
	if strings.HasPrefix(bodyStr, "event:") || strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") {
		// Extract JSON from SSE data line
		for _, line := range strings.Split(bodyStr, "\n") {
			if strings.HasPrefix(line, "data:") {
				jsonData = []byte(strings.TrimPrefix(line, "data:"))
				jsonData = []byte(strings.TrimSpace(string(jsonData)))
				break
			}
		}
	}

	// Parse MCP response
	var mcpResp MCPResponse
	if err := json.Unmarshal(jsonData, &mcpResp); err != nil {
		// Return raw body if not valid JSON-RPC
		return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
	}

	if mcpResp.Error != nil {
		return nil, fmt.Errorf("MCP error %d: %s", mcpResp.Error.Code, mcpResp.Error.Message)
	}

	if mcpResp.Result != nil {
		return &MCPCallResult{Result: mcpResp.Result, TraceID: traceID, SpanID: spanID}, nil
	}

	return &MCPCallResult{Result: body, TraceID: traceID, SpanID: spanID}, nil
}
