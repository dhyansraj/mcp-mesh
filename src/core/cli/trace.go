package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// TraceSpan represents a span in the trace tree
type TraceSpan struct {
	TraceID      string  `json:"TraceID"`
	SpanID       string  `json:"SpanID"`
	ParentSpan   *string `json:"ParentSpan,omitempty"`
	AgentName    string  `json:"AgentName"`
	AgentID      string  `json:"AgentID"`
	IPAddress    string  `json:"IPAddress"`
	Operation    string  `json:"Operation"`
	StartTime    string  `json:"StartTime"`
	EndTime      *string `json:"EndTime,omitempty"`
	DurationMS   *int64  `json:"DurationMS,omitempty"`
	Success      *bool   `json:"Success,omitempty"`
	ErrorMessage *string `json:"ErrorMessage,omitempty"`
	Capability   *string `json:"Capability,omitempty"`
	TargetAgent  *string `json:"TargetAgent,omitempty"`
	Runtime      string  `json:"Runtime,omitempty"`
}

// CompletedTraceResponse represents the registry's trace response
type CompletedTraceResponse struct {
	TraceID    string       `json:"TraceID"`
	Spans      []*TraceSpan `json:"Spans"`
	StartTime  string       `json:"StartTime"`
	EndTime    string       `json:"EndTime"`
	Duration   int64        `json:"Duration"`
	Success    bool         `json:"Success"`
	SpanCount  int          `json:"SpanCount"`
	AgentCount int          `json:"AgentCount"`
	Agents     []string     `json:"Agents"`
}

// TraceTreeNode represents a node in the trace tree for display
type TraceTreeNode struct {
	Span     *TraceSpan
	Children []*TraceTreeNode
}

// NewTraceCommand creates the trace command
func NewTraceCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "trace <trace_id>",
		Short: "Display distributed call trace",
		Long: `Query and display the call tree for a distributed trace.

Use with 'meshctl call --trace' to get trace IDs, then view the full
call tree with this command.

Examples:
  meshctl trace abc123def456789                    # View trace by ID
  meshctl trace abc123def456789 --json             # Output as JSON
  meshctl trace abc123def456789 --registry-url http://remote:8000  # Remote registry`,
		Args: cobra.ExactArgs(1),
		RunE: runTraceCommand,
	}

	// Registry connection flags
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
	cmd.Flags().Int("timeout", 30, "Request timeout in seconds")

	// Output options
	cmd.Flags().Bool("json", false, "Output as JSON")
	cmd.Flags().Bool("show-internal", false, "Show internal wrapper spans (proxy_call_wrapper, etc.)")

	// Retry options
	cmd.Flags().Int("retries", 3, "Number of retries when trace is not yet available")
	cmd.Flags().Int("retry-delay", 2, "Delay in seconds between retries")

	return cmd
}

func runTraceCommand(cmd *cobra.Command, args []string) error {
	traceID := args[0]

	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get registry connection flags
	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	insecure, _ := cmd.Flags().GetBool("insecure")
	timeout, _ := cmd.Flags().GetInt("timeout")
	jsonOutput, _ := cmd.Flags().GetBool("json")
	showInternal, _ := cmd.Flags().GetBool("show-internal")

	// Determine final registry URL
	finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)

	// Create HTTP client
	httpClient := createHTTPClient(timeout, insecure)

	// Get retry flags
	retries, _ := cmd.Flags().GetInt("retries")
	if retries < 0 {
		retries = 0
	}
	retryDelay, _ := cmd.Flags().GetInt("retry-delay")
	if retryDelay < 0 {
		retryDelay = 0
	}

	// Query trace from registry with retries
	var trace *CompletedTraceResponse
	maxAttempts := 1 + retries
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		trace, err = queryTrace(httpClient, finalRegistryURL, traceID)
		if err != nil {
			if attempt < maxAttempts {
				fmt.Fprintf(os.Stderr, "Error querying trace: %v, retrying (%d/%d)...\n", err, attempt, retries)
				time.Sleep(time.Duration(retryDelay) * time.Second)
				continue
			}
			return fmt.Errorf("failed to query trace: %w", err)
		}
		if trace == nil {
			if attempt < maxAttempts {
				fmt.Fprintf(os.Stderr, "Trace not yet available, retrying (%d/%d)...\n", attempt, retries)
				time.Sleep(time.Duration(retryDelay) * time.Second)
				continue
			}
			return fmt.Errorf("trace '%s' not found\n\n"+
				"Possible reasons:\n"+
				"  - Trace ID may be incorrect or expired\n"+
				"  - Distributed tracing may not be enabled\n"+
				"  - Observability stack (Tempo) may not be deployed\n\n"+
				"Run 'meshctl man observability' for setup instructions.", traceID)
		}
		break
	}

	// Output result
	if jsonOutput {
		output, _ := json.MarshalIndent(trace, "", "  ")
		fmt.Println(string(output))
	} else {
		printTraceTree(trace, showInternal)
	}

	return nil
}

// queryTrace queries the registry for a trace by ID
func queryTrace(client *http.Client, registryURL, traceID string) (*CompletedTraceResponse, error) {
	url := fmt.Sprintf("%s/trace/%s", registryURL, traceID)

	resp, err := client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry: %w\n\n"+
			"Hint: Ensure the registry and observability stack are running.\n"+
			"      Run 'meshctl scaffold --compose --observability' to generate docker-compose with Tempo.\n"+
			"      See 'meshctl man observability' for details.", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("registry returned status %d: %s", resp.StatusCode, string(body))
	}

	var trace CompletedTraceResponse
	if err := json.NewDecoder(resp.Body).Decode(&trace); err != nil {
		return nil, fmt.Errorf("failed to parse trace response: %w", err)
	}

	return &trace, nil
}

// printTraceTree prints the trace as a formatted tree
func printTraceTree(trace *CompletedTraceResponse, showInternal bool) {
	// Header
	fmt.Printf("Call Tree for trace %s\n", trace.TraceID)
	fmt.Println(strings.Repeat("═", 60))
	fmt.Println()

	// Build tree structure
	tree := buildTraceTree(trace.Spans, showInternal)

	// Print tree
	for i, root := range tree {
		isLast := i == len(tree)-1
		printTreeNode(root, "", isLast)
	}

	// Summary
	fmt.Println()
	fmt.Println(strings.Repeat("─", 60))

	// Parse duration from nanoseconds
	durationStr := formatTraceDuration(trace.Duration)

	statusIcon := "✓"
	if !trace.Success {
		statusIcon = "✗"
	}

	fmt.Printf("Summary: %d spans across %d agents | %s | %s\n",
		trace.SpanCount, trace.AgentCount, durationStr, statusIcon)
	fmt.Printf("Agents: %s\n", strings.Join(trace.Agents, ", "))
}

// buildTraceTree builds a tree structure from flat span list
func buildTraceTree(spans []*TraceSpan, showInternal bool) []*TraceTreeNode {
	// Create nodes for all spans
	nodeMap := make(map[string]*TraceTreeNode)
	for _, span := range spans {
		nodeMap[span.SpanID] = &TraceTreeNode{
			Span:     span,
			Children: make([]*TraceTreeNode, 0),
		}
	}

	// Build parent-child relationships
	var roots []*TraceTreeNode
	for _, span := range spans {
		node := nodeMap[span.SpanID]
		if span.ParentSpan != nil && *span.ParentSpan != "" {
			if parent, exists := nodeMap[*span.ParentSpan]; exists {
				parent.Children = append(parent.Children, node)
			} else {
				// Parent not found, treat as root
				roots = append(roots, node)
			}
		} else {
			// No parent, this is a root
			roots = append(roots, node)
		}
	}

	// Sort children by start time
	for _, node := range nodeMap {
		sort.Slice(node.Children, func(i, j int) bool {
			return node.Children[i].Span.StartTime < node.Children[j].Span.StartTime
		})
	}

	// Sort roots by start time
	sort.Slice(roots, func(i, j int) bool {
		return roots[i].Span.StartTime < roots[j].Span.StartTime
	})

	// Collapse internal wrapper spans unless --show-internal is set
	if !showInternal {
		roots = collapseWrapperSpans(roots)
	}

	return roots
}

// collapseWrapperSpans removes internal wrapper spans and re-parents their children
// This makes the trace tree cleaner by hiding implementation details
func collapseWrapperSpans(nodes []*TraceTreeNode) []*TraceTreeNode {
	var result []*TraceTreeNode

	for _, node := range nodes {
		// Recursively process children first
		node.Children = collapseWrapperSpans(node.Children)

		// Check if this is a wrapper span that should be collapsed
		if isWrapperSpan(node.Span.Operation) {
			// Skip this node, promote its children to the parent level
			result = append(result, node.Children...)
		} else {
			result = append(result, node)
		}
	}

	// Re-sort by start time after collapsing
	sort.Slice(result, func(i, j int) bool {
		return result[i].Span.StartTime < result[j].Span.StartTime
	})

	return result
}

// isWrapperSpan returns true if the operation is an internal wrapper that should be hidden
func isWrapperSpan(operation string) bool {
	// Prefixes of internal wrapper operations to hide from trace display
	// Using prefix matching for flexibility (e.g., proxy_call_wrapper_v2)
	wrapperPrefixes := []string{
		"proxy_call_wrapper",
		"_internal_",
	}

	for _, prefix := range wrapperPrefixes {
		if strings.HasPrefix(operation, prefix) {
			return true
		}
	}
	return false
}

// printTreeNode prints a single node and its children
func printTreeNode(node *TraceTreeNode, prefix string, isLast bool) {
	// Determine connector
	connector := "├─"
	if isLast {
		connector = "└─"
	}

	// Format duration
	durationStr := ""
	if node.Span.DurationMS != nil {
		durationStr = fmt.Sprintf("[%dms]", *node.Span.DurationMS)
	}

	// Format status
	statusIcon := "✓"
	if node.Span.Success != nil && !*node.Span.Success {
		statusIcon = "✗"
	}

	// Print node
	fmt.Printf("%s%s %s (%s) %s %s\n",
		prefix, connector,
		node.Span.Operation,
		node.Span.AgentName,
		durationStr,
		statusIcon)

	// Print error message if present
	if node.Span.ErrorMessage != nil && *node.Span.ErrorMessage != "" {
		childPrefix := prefix
		if isLast {
			childPrefix += "   "
		} else {
			childPrefix += "│  "
		}
		fmt.Fprintf(os.Stderr, "%s   Error: %s\n", childPrefix, *node.Span.ErrorMessage)
	}

	// Print children
	childPrefix := prefix
	if isLast {
		childPrefix += "   "
	} else {
		childPrefix += "│  "
	}

	for i, child := range node.Children {
		childIsLast := i == len(node.Children)-1
		printTreeNode(child, childPrefix, childIsLast)
	}
}

// formatTraceDuration formats nanoseconds as human readable duration
func formatTraceDuration(nanos int64) string {
	d := time.Duration(nanos)
	if d < time.Millisecond {
		return fmt.Sprintf("%dµs", d.Microseconds())
	}
	if d < time.Second {
		return fmt.Sprintf("%dms", d.Milliseconds())
	}
	return fmt.Sprintf("%.2fs", d.Seconds())
}
