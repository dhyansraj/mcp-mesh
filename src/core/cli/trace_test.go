package cli

import (
	"testing"
	"time"
)

func TestIsWrapperSpan(t *testing.T) {
	tests := []struct {
		operation string
		expected  bool
	}{
		// Wrapper spans that should be hidden
		{"proxy_call_wrapper", true},
		{"proxy_call_wrapper_v2", true},
		{"_internal_span", true},
		{"_internal_", true},

		// Regular operations that should be shown
		{"smart_analyze", false},
		{"get_current_time", false},
		{"fetch_system_overview", false},
		{"process_chat", false},
		{"GET /api/tools", false},
		{"POST /mcp", false},
	}

	for _, tt := range tests {
		t.Run(tt.operation, func(t *testing.T) {
			result := isWrapperSpan(tt.operation)
			if result != tt.expected {
				t.Errorf("isWrapperSpan(%q) = %v, expected %v", tt.operation, result, tt.expected)
			}
		})
	}
}

func TestFormatTraceDuration(t *testing.T) {
	tests := []struct {
		nanos    int64
		expected string
	}{
		// Microseconds
		{500, "0µs"},
		{500000, "500µs"},
		{999999, "999µs"},

		// Milliseconds
		{int64(time.Millisecond), "1ms"},
		{int64(50 * time.Millisecond), "50ms"},
		{int64(999 * time.Millisecond), "999ms"},

		// Seconds
		{int64(time.Second), "1.00s"},
		{int64(2500 * time.Millisecond), "2.50s"},
		{int64(10 * time.Second), "10.00s"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			result := formatTraceDuration(tt.nanos)
			if result != tt.expected {
				t.Errorf("formatTraceDuration(%d) = %q, expected %q", tt.nanos, result, tt.expected)
			}
		})
	}
}

func TestBuildTraceTree(t *testing.T) {
	// Test basic tree building with wrapper span collapse
	parentSpan := "parent123"
	spans := []*TraceSpan{
		{SpanID: "root", ParentSpan: nil, Operation: "smart_analyze", AgentName: "llm-agent", StartTime: "2024-01-01T00:00:00Z"},
		{SpanID: "wrapper1", ParentSpan: &parentSpan, Operation: "proxy_call_wrapper", AgentName: "llm-agent", StartTime: "2024-01-01T00:00:01Z"},
		{SpanID: "child1", ParentSpan: &parentSpan, Operation: "get_time", AgentName: "time-agent", StartTime: "2024-01-01T00:00:02Z"},
	}

	// Test with showInternal=false (default behavior)
	tree := buildTraceTree(spans, false)

	// Wrapper span should be collapsed
	wrapperFound := false
	for _, node := range tree {
		if node.Span.Operation == "proxy_call_wrapper" {
			wrapperFound = true
		}
	}
	if wrapperFound {
		t.Error("Wrapper span should be collapsed when showInternal=false")
	}

	// Test with showInternal=true
	treeWithInternal := buildTraceTree(spans, true)

	// Wrapper span should be present
	wrapperFoundWithInternal := false
	var checkNodes func([]*TraceTreeNode)
	checkNodes = func(nodes []*TraceTreeNode) {
		for _, node := range nodes {
			if node.Span.Operation == "proxy_call_wrapper" {
				wrapperFoundWithInternal = true
			}
			checkNodes(node.Children)
		}
	}
	checkNodes(treeWithInternal)

	if !wrapperFoundWithInternal {
		t.Error("Wrapper span should be present when showInternal=true")
	}
}
