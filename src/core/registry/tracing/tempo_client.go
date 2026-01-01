package tracing

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

// TempoClient queries traces from Grafana Tempo
type TempoClient struct {
	endpoint   string
	httpClient *http.Client
}

// TempoTraceResponse represents the response from Tempo's trace API
type TempoTraceResponse struct {
	Batches []TempoBatch `json:"batches"`
}

// TempoBatch represents a batch of spans from Tempo
type TempoBatch struct {
	Resource   TempoResource    `json:"resource"`
	ScopeSpans []TempoScopeSpan `json:"scopeSpans"`
}

// TempoResource represents the resource attributes
type TempoResource struct {
	Attributes []TempoAttribute `json:"attributes"`
}

// TempoScopeSpan represents instrumentation scope spans
type TempoScopeSpan struct {
	Scope TempoScope  `json:"scope"`
	Spans []TempoSpan `json:"spans"`
}

// TempoScope represents the instrumentation scope
type TempoScope struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// TempoSpan represents a single span from Tempo
type TempoSpan struct {
	TraceID           string           `json:"traceId"`
	SpanID            string           `json:"spanId"`
	ParentSpanID      string           `json:"parentSpanId,omitempty"`
	Name              string           `json:"name"`
	Kind              string           `json:"kind"` // e.g., "SPAN_KIND_INTERNAL"
	StartTimeUnixNano string           `json:"startTimeUnixNano"`
	EndTimeUnixNano   string           `json:"endTimeUnixNano"`
	Attributes        []TempoAttribute `json:"attributes"`
	Status            TempoStatus      `json:"status"`
}

// TempoAttribute represents a key-value attribute
type TempoAttribute struct {
	Key   string     `json:"key"`
	Value TempoValue `json:"value"`
}

// TempoValue represents an attribute value
type TempoValue struct {
	StringValue string `json:"stringValue,omitempty"`
	IntValue    string `json:"intValue,omitempty"`
	BoolValue   *bool  `json:"boolValue,omitempty"`
}

// TempoStatus represents span status
type TempoStatus struct {
	Code    string `json:"code"` // e.g., "STATUS_CODE_OK", "STATUS_CODE_ERROR"
	Message string `json:"message,omitempty"`
}

// NewTempoClient creates a new Tempo client
func NewTempoClient(endpoint string) *TempoClient {
	// Ensure endpoint doesn't have trailing slash
	endpoint = strings.TrimSuffix(endpoint, "/")

	return &TempoClient{
		endpoint: endpoint,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// GetTempoURLFromEnv returns the Tempo query URL from environment variables
func GetTempoURLFromEnv() string {
	// Check for TEMPO_URL first (preferred for querying)
	tempoURL := os.Getenv("TEMPO_URL")
	if tempoURL != "" {
		return tempoURL
	}

	// Fallback: construct from TELEMETRY_ENDPOINT (replace gRPC port with HTTP port)
	telemetryEndpoint := os.Getenv("TELEMETRY_ENDPOINT")
	if telemetryEndpoint != "" {
		// Convert tempo:4317 (gRPC) to http://tempo:3200 (HTTP API)
		host := strings.Split(telemetryEndpoint, ":")[0]
		return fmt.Sprintf("http://%s:3200", host)
	}

	return ""
}

// GetTrace retrieves a trace by ID from Tempo
func (tc *TempoClient) GetTrace(traceID string) (*CompletedTrace, error) {
	// Normalize trace ID (remove dashes if present)
	normalizedID := strings.ReplaceAll(traceID, "-", "")

	// Query Tempo API
	url := fmt.Sprintf("%s/api/traces/%s", tc.endpoint, normalizedID)

	resp, err := tc.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to query Tempo: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		return nil, nil // Trace not found
	}

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("Tempo returned status %d: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read Tempo response: %w", err)
	}

	var tempoResp TempoTraceResponse
	if err := json.Unmarshal(body, &tempoResp); err != nil {
		return nil, fmt.Errorf("failed to parse Tempo response: %w", err)
	}

	// Convert Tempo response to CompletedTrace
	return tc.convertTempoToCompletedTrace(traceID, &tempoResp)
}

// convertTempoToCompletedTrace converts Tempo's response format to CompletedTrace
func (tc *TempoClient) convertTempoToCompletedTrace(traceID string, tempoResp *TempoTraceResponse) (*CompletedTrace, error) {
	var spans []*TraceSpan
	agentSet := make(map[string]bool)

	for _, batch := range tempoResp.Batches {
		// Extract service name from resource attributes
		serviceName := tc.getServiceName(batch.Resource.Attributes)

		for _, scopeSpan := range batch.ScopeSpans {
			for _, span := range scopeSpan.Spans {
				traceSpan := tc.convertTempoSpan(&span, serviceName)
				spans = append(spans, traceSpan)
				agentSet[traceSpan.AgentName] = true
			}
		}
	}

	if len(spans) == 0 {
		return nil, nil
	}

	// Sort spans by start time
	sort.Slice(spans, func(i, j int) bool {
		return spans[i].StartTime.Before(spans[j].StartTime)
	})

	// Calculate trace timing
	startTime := spans[0].StartTime
	endTime := spans[0].StartTime
	success := true

	for _, span := range spans {
		if span.StartTime.Before(startTime) {
			startTime = span.StartTime
		}
		if span.EndTime != nil && span.EndTime.After(endTime) {
			endTime = *span.EndTime
		}
		if span.Success != nil && !*span.Success {
			success = false
		}
	}

	// Build agent list
	agents := make([]string, 0, len(agentSet))
	for agent := range agentSet {
		agents = append(agents, agent)
	}
	sort.Strings(agents)

	return &CompletedTrace{
		TraceID:    traceID,
		Spans:      spans,
		StartTime:  startTime,
		EndTime:    endTime,
		Duration:   endTime.Sub(startTime),
		Success:    success,
		SpanCount:  len(spans),
		AgentCount: len(agents),
		Agents:     agents,
	}, nil
}

// convertTempoSpan converts a Tempo span to TraceSpan
func (tc *TempoClient) convertTempoSpan(span *TempoSpan, serviceName string) *TraceSpan {
	// Parse timestamps (nanoseconds since epoch as string)
	startNano := parseNanoTimestamp(span.StartTimeUnixNano)
	endNano := parseNanoTimestamp(span.EndTimeUnixNano)

	startTime := time.Unix(0, startNano)
	endTime := time.Unix(0, endNano)

	// Calculate duration
	durationMS := (endNano - startNano) / 1e6

	// Extract attributes
	agentID := ""
	operation := span.Name
	capability := ""
	targetAgent := ""
	runtime := ""
	ipAddress := ""

	for _, attr := range span.Attributes {
		switch attr.Key {
		case "mcp.agent.id":
			agentID = attr.Value.StringValue
		case "mcp.operation":
			operation = attr.Value.StringValue
		case "mcp.capability":
			capability = attr.Value.StringValue
		case "mcp.target.agent", "mcp.target_agent":
			targetAgent = attr.Value.StringValue
		case "mcp.runtime":
			runtime = attr.Value.StringValue
		case "mcp.ip.address", "mcp.agent.ip":
			ipAddress = attr.Value.StringValue
		}
	}

	// Determine success from status code string
	// STATUS_CODE_OK = success, STATUS_CODE_ERROR = failure, others = unknown (treat as success)
	success := span.Status.Code != "STATUS_CODE_ERROR"
	var errorMessage *string
	if span.Status.Message != "" {
		errorMessage = &span.Status.Message
	}

	// Handle parent span
	var parentSpan *string
	if span.ParentSpanID != "" {
		parentSpan = &span.ParentSpanID
	}

	return &TraceSpan{
		TraceID:      span.TraceID,
		SpanID:       span.SpanID,
		ParentSpan:   parentSpan,
		AgentName:    serviceName,
		AgentID:      agentID,
		IPAddress:    ipAddress,
		Operation:    operation,
		StartTime:    startTime,
		EndTime:      &endTime,
		DurationMS:   &durationMS,
		Success:      &success,
		ErrorMessage: errorMessage,
		Capability:   stringPtrIfNotEmpty(capability),
		TargetAgent:  stringPtrIfNotEmpty(targetAgent),
		Runtime:      runtime,
	}
}

// getServiceName extracts service.name from resource attributes
func (tc *TempoClient) getServiceName(attrs []TempoAttribute) string {
	for _, attr := range attrs {
		if attr.Key == "service.name" {
			return attr.Value.StringValue
		}
	}
	return "unknown"
}

// parseNanoTimestamp parses a nanosecond timestamp string
func parseNanoTimestamp(s string) int64 {
	if s == "" {
		return 0
	}
	nano, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0 // Return epoch time on parse error
	}
	return nano
}

// stringPtrIfNotEmpty returns a pointer to s if not empty, nil otherwise
func stringPtrIfNotEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
