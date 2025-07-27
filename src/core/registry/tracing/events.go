package tracing

import (
	"encoding/json"
	"fmt"
	"strconv"
	"time"
)

// TraceEvent represents a trace event matching the Python runtime schema
// This structure must be compatible with the Python TraceEvent in:
// src/runtime/python/_mcp_mesh/tracing/events.py
type TraceEvent struct {
	TraceID      string  `json:"trace_id"`
	SpanID       string  `json:"span_id"`
	ParentSpan   *string `json:"parent_span,omitempty"`
	AgentName    string  `json:"agent_name"`
	AgentID      string  `json:"agent_id"`
	IPAddress    string  `json:"ip_address"`
	Operation    string  `json:"operation"`
	EventType    string  `json:"event_type"` // span_start, span_end, error
	Timestamp    float64 `json:"timestamp"`
	DurationMS   *int64  `json:"duration_ms,omitempty"`
	Success      *bool   `json:"success,omitempty"`
	ErrorMessage *string `json:"error_message,omitempty"`
	Capability   *string `json:"capability,omitempty"`
	TargetAgent  *string `json:"target_agent,omitempty"`
	Runtime      string  `json:"runtime"`
}

// ToRedisMap converts TraceEvent to Redis-compatible map[string]interface{}
// This matches the Python to_dict() method for Redis XADD compatibility
func (te *TraceEvent) ToRedisMap() map[string]interface{} {
	result := make(map[string]interface{})

	// Always include required fields
	result["trace_id"] = te.TraceID
	result["span_id"] = te.SpanID
	result["agent_name"] = te.AgentName
	result["agent_id"] = te.AgentID
	result["ip_address"] = te.IPAddress
	result["operation"] = te.Operation
	result["event_type"] = te.EventType
	result["timestamp"] = strconv.FormatFloat(te.Timestamp, 'f', -1, 64)
	result["runtime"] = te.Runtime

	// Include optional fields only if they have values
	if te.ParentSpan != nil {
		result["parent_span"] = *te.ParentSpan
	}
	if te.DurationMS != nil {
		result["duration_ms"] = strconv.FormatInt(*te.DurationMS, 10)
	}
	if te.Success != nil {
		// Convert boolean to string for Redis compatibility (matches Python implementation)
		if *te.Success {
			result["success"] = "true"
		} else {
			result["success"] = "false"
		}
	}
	if te.ErrorMessage != nil {
		result["error_message"] = *te.ErrorMessage
	}
	if te.Capability != nil {
		result["capability"] = *te.Capability
	}
	if te.TargetAgent != nil {
		result["target_agent"] = *te.TargetAgent
	}

	return result
}

// FromRedisMap creates TraceEvent from Redis stream data
func (te *TraceEvent) FromRedisMap(data map[string]interface{}) error {
	// Required fields
	te.TraceID = getString(data, "trace_id")
	te.SpanID = getString(data, "span_id")
	te.AgentName = getString(data, "agent_name")
	te.AgentID = getString(data, "agent_id")

	// Handle both IP field names (Go and Python compatibility)
	te.IPAddress = getString(data, "ip_address")
	if te.IPAddress == "" {
		te.IPAddress = getString(data, "agent_ip")
	}

	// Handle both operation field names (Go uses "operation", Python uses "function_name")
	te.Operation = getString(data, "operation")
	if te.Operation == "" {
		te.Operation = getString(data, "function_name")
	}

	te.EventType = getString(data, "event_type")

	// Default runtime to "python" if not specified
	te.Runtime = getString(data, "runtime")
	if te.Runtime == "" {
		te.Runtime = "python"
	}

	// Parse timestamp (Go uses "timestamp", Python uses "start_time")
	if timestampStr := getString(data, "timestamp"); timestampStr != "" {
		if timestamp, err := strconv.ParseFloat(timestampStr, 64); err == nil {
			te.Timestamp = timestamp
		}
	} else if startTimeStr := getString(data, "start_time"); startTimeStr != "" {
		if startTime, err := strconv.ParseFloat(startTimeStr, 64); err == nil {
			te.Timestamp = startTime
		}
	}

	// Optional fields
	if parentSpan := getString(data, "parent_span"); parentSpan != "" {
		te.ParentSpan = &parentSpan
	}

	if durationStr := getString(data, "duration_ms"); durationStr != "" {
		if duration, err := strconv.ParseInt(durationStr, 10, 64); err == nil {
			te.DurationMS = &duration
		} else {
			// Try parsing as float and convert to int64 milliseconds
			if durationFloat, err := strconv.ParseFloat(durationStr, 64); err == nil {
				durationInt := int64(durationFloat)
				te.DurationMS = &durationInt
			}
		}
	} else {
		// Debug: log all fields to see what's available
		fmt.Printf("DEBUG: No duration_ms found. Available fields: %+v\n", data)
	}

	if successStr := getString(data, "success"); successStr != "" {
		// Parse boolean from string (handle both Python "True"/"False" and Go "true"/"false")
		success := successStr == "true" || successStr == "True"
		te.Success = &success
	}

	if errorMessage := getString(data, "error_message"); errorMessage != "" {
		te.ErrorMessage = &errorMessage
	}

	if capability := getString(data, "capability"); capability != "" {
		te.Capability = &capability
	}

	if targetAgent := getString(data, "target_agent"); targetAgent != "" {
		te.TargetAgent = &targetAgent
	}

	return nil
}

// getString safely extracts string value from Redis data map
func getString(data map[string]interface{}, key string) string {
	if value, exists := data[key]; exists {
		if strVal, ok := value.(string); ok {
			return strVal
		}
	}
	return ""
}

// NewSpanStartEvent creates a span start event
func NewSpanStartEvent(traceID, spanID string, parentSpan *string, agentName, agentID, ipAddress, operation string, capability *string, targetAgent *string) *TraceEvent {
	event := &TraceEvent{
		TraceID:    traceID,
		SpanID:     spanID,
		ParentSpan: parentSpan,
		AgentName:  agentName,
		AgentID:    agentID,
		IPAddress:  ipAddress,
		Operation:  operation,
		EventType:  "span_start",
		Timestamp:  float64(time.Now().UnixNano()) / 1e9, // Unix timestamp with nanosecond precision
		Runtime:    "go",
	}

	if capability != nil {
		event.Capability = capability
	}
	if targetAgent != nil {
		event.TargetAgent = targetAgent
	}

	return event
}

// NewSpanEndEvent creates a span end event
func NewSpanEndEvent(traceID, spanID string, agentName, agentID, ipAddress, operation string, durationMS *int64, success bool, errorMessage *string) *TraceEvent {
	event := &TraceEvent{
		TraceID:    traceID,
		SpanID:     spanID,
		AgentName:  agentName,
		AgentID:    agentID,
		IPAddress:  ipAddress,
		Operation:  operation,
		EventType:  "span_end",
		Timestamp:  float64(time.Now().UnixNano()) / 1e9,
		Success:    &success,
		Runtime:    "go",
	}

	if durationMS != nil {
		event.DurationMS = durationMS
	}
	if errorMessage != nil {
		event.ErrorMessage = errorMessage
	}

	return event
}

// NewErrorEvent creates an error event
func NewErrorEvent(traceID, spanID string, agentName, agentID, ipAddress, operation, errorMessage string) *TraceEvent {
	success := false
	return &TraceEvent{
		TraceID:      traceID,
		SpanID:       spanID,
		AgentName:    agentName,
		AgentID:      agentID,
		IPAddress:    ipAddress,
		Operation:    operation,
		EventType:    "error",
		Timestamp:    float64(time.Now().UnixNano()) / 1e9,
		Success:      &success,
		ErrorMessage: &errorMessage,
		Runtime:      "go",
	}
}

// ToJSON serializes the trace event to JSON
func (te *TraceEvent) ToJSON() ([]byte, error) {
	return json.Marshal(te)
}

// FromJSON deserializes the trace event from JSON
func (te *TraceEvent) FromJSON(data []byte) error {
	return json.Unmarshal(data, te)
}
