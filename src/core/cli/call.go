package cli

import (
	"bytes"
	"crypto/tls"
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

// NewCallCommand creates the call command
func NewCallCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "call [agent:]tool_name [arguments]",
		Short: "Call an MCP tool on an agent",
		Long: `Call an MCP tool on a registered agent.

The command discovers the agent endpoint via the registry and makes the MCP call
with proper headers. Arguments can be provided as JSON string or via --file flag.

Examples:
  meshctl call hello_mesh_simple                          # Call tool, discover agent via registry
  meshctl call weather-agent:get_weather                  # Specify agent explicitly
  meshctl call calculator:add '{"a": 1, "b": 2}'          # With JSON arguments
  meshctl call analyzer:process --file data.json          # Arguments from file
  meshctl call hello_mesh --registry-url http://remote:8000  # Remote registry
  meshctl call hello_mesh --registry-scheme https --insecure # HTTPS with self-signed cert
  meshctl call hello_mesh --agent-url http://localhost:8080  # Direct agent call (skip registry)

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

	// Ingress mode flags (for Kubernetes clusters with ingress)
	cmd.Flags().String("ingress-domain", "", "Ingress domain (e.g., mcp-mesh.local) - enables ingress mode")
	cmd.Flags().String("ingress-url", "", "Ingress base URL (e.g., http://192.168.58.2) - required if DNS not configured")

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
	}

	// Make MCP call
	var result json.RawMessage
	if ingressDomain != "" && agentURL == "" {
		// Ingress mode: need Host header
		result, err = callMCPToolWithHost(httpClient, agentEndpoint, agentHostHeader, toolName, toolArgs)
	} else {
		result, err = callMCPTool(httpClient, agentEndpoint, toolName, toolArgs)
	}
	if err != nil {
		return fmt.Errorf("MCP call failed: %w", err)
	}

	// Output result
	if raw {
		fmt.Println(string(result))
	} else {
		var prettyJSON bytes.Buffer
		if err := json.Indent(&prettyJSON, result, "", "  "); err != nil {
			fmt.Println(string(result))
		} else {
			fmt.Println(prettyJSON.String())
		}
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
func callMCPToolWithHost(client *http.Client, endpoint, hostHeader, toolName string, args map[string]interface{}) (json.RawMessage, error) {
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

	// Set Host header for ingress routing
	if hostHeader != "" {
		req.Host = hostHeader
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to call agent at %s (Host: %s): %w", mcpURL, hostHeader, err)
	}
	defer resp.Body.Close()

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
		return body, nil
	}

	if mcpResp.Error != nil {
		return nil, fmt.Errorf("MCP error %d: %s", mcpResp.Error.Code, mcpResp.Error.Message)
	}

	if mcpResp.Result != nil {
		return mcpResp.Result, nil
	}

	return body, nil
}

// callMCPTool makes an MCP tools/call request to the agent
func callMCPTool(client *http.Client, endpoint, toolName string, args map[string]interface{}) (json.RawMessage, error) {
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

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to call agent at %s: %w", mcpURL, err)
	}
	defer resp.Body.Close()

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
		return body, nil
	}

	if mcpResp.Error != nil {
		return nil, fmt.Errorf("MCP error %d: %s", mcpResp.Error.Code, mcpResp.Error.Message)
	}

	if mcpResp.Result != nil {
		return mcpResp.Result, nil
	}

	return body, nil
}
